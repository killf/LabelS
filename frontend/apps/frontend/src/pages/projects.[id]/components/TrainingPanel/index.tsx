import { useState } from 'react';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Popover,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';

import { getProjectModels } from '@/api/services/project';
import {
  clearTrainingLogs,
  deleteTrainingRun,
  downloadModel,
  getTrainingLog,
  getTrainingParameters,
  getTrainingRuns,
  startTraining,
} from '@/api/services/training';
import type { TrainingParameters, TrainingRun, TrainingStatus } from '@/api/services/training';
import { message } from '@/StaticAnt';

const statuses: Record<TrainingStatus, { text: string; color: string }> = {
  PENDING: { text: '等待启动', color: 'default' },
  RUNNING: { text: '训练中', color: 'processing' },
  SUCCEEDED: { text: '成功', color: 'success' },
  FAILED: { text: '失败', color: 'error' },
  INTERRUPTED: { text: '已中断', color: 'warning' },
};

const active = (status: TrainingStatus) => status === 'PENDING' || status === 'RUNNING';
const time = (value: string | null) => (value ? new Date(value).toLocaleString() : '-');

type TrainingFormValues = Omit<TrainingParameters, 'extra_params'> & { extra_params?: string };

function parseExtraParams(value?: string): Record<string, unknown> {
  let parameters: unknown;
  try {
    parameters = value?.trim() ? JSON.parse(value) : {};
  } catch {
    throw new Error('请输入合法的 JSON');
  }
  if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) {
    throw new Error('自定义训练参数必须是 JSON 对象');
  }
  return parameters as Record<string, unknown>;
}

export default function TrainingPanel({ projectId, canClean }: { projectId: number; canClean: boolean }) {
  const [showStart, setShowStart] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [selectedRun, setSelectedRun] = useState<TrainingRun>();
  const [page, setPage] = useState(1);
  const [cleaning, setCleaning] = useState<number>();
  const [showParameters, setShowParameters] = useState(false);
  const [parameterSearch, setParameterSearch] = useState('');
  const [form] = Form.useForm<TrainingFormValues>();
  const parameters = useQuery({
    queryKey: ['trainingParameters', projectId],
    queryFn: () => getTrainingParameters(projectId),
    enabled: showParameters,
  });
  const runs = useQuery({
    queryKey: ['trainingRuns', projectId, page],
    queryFn: () => getTrainingRuns(projectId, page - 1),
    refetchInterval: (query) => (query.state.data?.data.some((run) => active(run.status)) ? 2000 : false),
  });
  const models = useQuery({
    queryKey: ['projectModels', projectId],
    queryFn: () => getProjectModels(projectId),
    enabled: showStart || showHistory,
  });
  const logs = useQuery({
    queryKey: ['trainingLog', projectId, selectedRun?.id],
    queryFn: () => getTrainingLog(projectId, selectedRun!.id),
    enabled: Boolean(selectedRun),
    refetchInterval: () =>
      runs.data?.data.some((run) => run.id === selectedRun?.id && active(run.status)) ? 2000 : false,
  });
  const start = useMutation({
    mutationFn: (values: TrainingParameters) => startTraining(projectId, values),
    onSuccess: () => {
      setShowStart(false);
      setPage(1);
      setShowHistory(true);
      void runs.refetch();
      message.success('训练已提交，可在训练记录中查看状态');
    },
  });
  const busy = runs.data?.data.some((run) => active(run.status));
  const cleanup = async (run: TrainingRun, includeModel: boolean) => {
    setCleaning(run.id);
    try {
      if (includeModel) await deleteTrainingRun(projectId, run.id);
      else await clearTrainingLogs(projectId, run.id);
      if (selectedRun?.id === run.id) setSelectedRun(undefined);
      message.success(includeModel ? '执行记录、模型和日志已删除' : '日志已清理，执行记录和模型已保留');
      await runs.refetch();
      if (includeModel) await models.refetch();
    } finally {
      setCleaning(undefined);
    }
  };

  return (
    <>
      <Space>
        <Button type="primary" ghost disabled={busy} onClick={() => setShowStart(true)}>
          开始训练
        </Button>
        <Button
          onClick={() => {
            setPage(1);
            setShowHistory(true);
            void runs.refetch();
          }}
        >
          训练记录{busy ? '（训练中）' : ''}
        </Button>
      </Space>
      <Modal
        title="开始训练"
        open={showStart}
        onCancel={() => setShowStart(false)}
        confirmLoading={start.isPending}
        onOk={() => form.submit()}
        okText="开始训练"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={({ extra_params, ...values }) =>
            start.mutate({ ...values, extra_params: parseExtraParams(extra_params) })
          }
          initialValues={{
            algorithm: 'yolo26_detect',
            initial_model: 'yolo26s.pt',
            epochs: 100,
            imgsz: 1024,
            batch: 2,
          }}
        >
          <Form.Item name="algorithm" label="算法" rules={[{ required: true }]}>
            <Select options={[{ value: 'yolo26_detect', label: 'YOLO26 目标检测' }]} />
          </Form.Item>
          <Form.Item name="initial_model" label="初始权重" rules={[{ required: true }]}>
            <Select
              options={[
                {
                  label: 'YOLO26 预训练模型',
                  options: ['n', 's', 'm', 'l', 'x'].map((size) => ({
                    value: `yolo26${size}.pt`,
                    label: `YOLO26${size}`,
                  })),
                },
                {
                  label: '本项目模型',
                  options: (models.data?.data ?? []).map((name) => ({ value: name, label: name })),
                },
              ]}
            />
          </Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
            <Form.Item name="epochs" label="训练轮数" rules={[{ required: true }]}>
              <InputNumber min={1} max={10000} precision={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="imgsz"
              label="图片尺寸（像素）"
              rules={[
                { required: true },
                {
                  validator: (_, value) =>
                    value % 32 === 0 ? Promise.resolve() : Promise.reject(new Error('图片尺寸需要是 32 的倍数')),
                },
              ]}
            >
              <InputNumber min={32} max={4096} step={32} precision={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="batch"
              label="每批图片数"
              rules={[
                { required: true },
                {
                  validator: (_, value) =>
                    value === -1 || value > 0 ? Promise.resolve() : Promise.reject(new Error('请输入 -1 或正整数')),
                },
              ]}
            >
              <InputNumber min={-1} max={1024} precision={0} style={{ width: '100%' }} />
            </Form.Item>
          </div>
          <Form.Item
            name="extra_params"
            label={
              <Space size={4}>
                自定义训练参数（JSON）
                <Button
                  type="text"
                  size="small"
                  aria-label="查看可修改的训练参数"
                  icon={<QuestionCircleOutlined />}
                  onClick={() => setShowParameters(true)}
                />
              </Space>
            }
            rules={[
              {
                validator: (_, value) => {
                  try {
                    parseExtraParams(value);
                    return Promise.resolve();
                  } catch (error) {
                    return Promise.reject(error);
                  }
                },
              },
            ]}
          >
            <Input.TextArea
              rows={5}
              spellCheck={false}
              style={{ fontFamily: 'monospace' }}
              placeholder={'{\n  "lr0": 0.001,\n  "amp": false\n}'}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="自定义训练参数说明"
        open={showParameters}
        onCancel={() => setShowParameters(false)}
        footer={null}
        width={900}
      >
        <Typography.Paragraph type="secondary">
          以下为可在 JSON 中追加的全部参数及默认值。基础表单和项目路径由系统管理，不在此列。
          部分参数仅适用于其他算法、推理或导出，YOLO26 目标检测训练时可能不生效。
        </Typography.Paragraph>
        <Input.Search
          aria-label="搜索训练参数"
          placeholder="搜索参数名或说明"
          allowClear
          value={parameterSearch}
          onChange={(event) => setParameterSearch(event.target.value)}
          style={{ marginBottom: 12 }}
        />
        {parameters.isError ? (
          <Alert
            type="error"
            message="无法加载参数说明"
            action={<Button onClick={() => void parameters.refetch()}>重试</Button>}
          />
        ) : (
          <Table
            rowKey="name"
            size="small"
            loading={parameters.isFetching}
            pagination={false}
            scroll={{ y: 420, x: 650 }}
            dataSource={parameters.data?.data.filter((parameter) =>
              `${parameter.name} ${parameter.description}`.toLowerCase().includes(parameterSearch.trim().toLowerCase()),
            )}
            columns={[
              { title: '参数', dataIndex: 'name', width: 160 },
              {
                title: '默认值',
                width: 130,
                render: (_, parameter) => <code>{JSON.stringify(parameter.default)}</code>,
              },
              { title: '说明', dataIndex: 'description' },
            ]}
          />
        )}
      </Modal>
      <Drawer title="训练记录" open={showHistory} onClose={() => setShowHistory(false)} width={1080}>
        <Table<TrainingRun>
          rowKey="id"
          loading={runs.isFetching && !runs.data}
          dataSource={runs.data?.data ?? []}
          pagination={{ current: page, pageSize: 10, total: runs.data?.meta_data.total, onChange: setPage }}
          columns={[
            { title: '编号', dataIndex: 'id', width: 65 },
            {
              title: '状态',
              render: (_, run) => <Tag color={statuses[run.status].color}>{statuses[run.status].text}</Tag>,
            },
            {
              title: '初始模型',
              render: (_, run) => (
                <Button
                  type="link"
                  disabled={!models.data?.data.includes(run.initial_model)}
                  style={{ padding: 0 }}
                  onClick={() => void downloadModel(projectId, run.initial_model)}
                >
                  {run.initial_model}
                </Button>
              ),
            },
            {
              title: '参数',
              render: (_, run) => (
                <Popover
                  trigger="click"
                  title="训练参数"
                  content={
                    <pre style={{ margin: 0, maxHeight: 360, maxWidth: 480, overflow: 'auto' }}>
                      {JSON.stringify(run.parameters, null, 2)}
                    </pre>
                  }
                >
                  <Button type="link" style={{ padding: 0, height: 'auto', whiteSpace: 'normal', textAlign: 'left' }}>
                    {run.parameters.epochs} 轮 / {run.parameters.imgsz}px / batch {run.parameters.batch}
                  </Button>
                </Popover>
              ),
            },
            { title: '开始时间', render: (_, run) => time(run.started_at) },
            { title: '结束时间', render: (_, run) => time(run.finished_at) },
            {
              title: '产出模型',
              render: (_, run) =>
                run.model_name ? (
                  <Button
                    type="link"
                    disabled={!run.model_available}
                    style={{ padding: 0 }}
                    onClick={() => void downloadModel(projectId, run.model_name!)}
                  >
                    {run.model_name}
                  </Button>
                ) : (
                  '-'
                ),
            },
            {
              title: '操作',
              width: 230,
              render: (_, run) => (
                <Space size={0} wrap>
                  <Button
                    type="link"
                    disabled={!run.log_available && !active(run.status)}
                    onClick={() => setSelectedRun(run)}
                  >
                    查看日志
                  </Button>
                  <Popconfirm title="清理日志和中间文件？执行记录及模型会保留。" onConfirm={() => cleanup(run, false)}>
                    <Button
                      type="link"
                      disabled={!canClean || active(run.status) || !run.log_available || cleaning === run.id}
                    >
                      清理日志
                    </Button>
                  </Popconfirm>
                  <Popconfirm
                    title="删除此记录、产出模型和全部日志？此操作不可恢复。"
                    onConfirm={() => cleanup(run, true)}
                  >
                    <Button type="link" danger disabled={!canClean || active(run.status) || cleaning === run.id}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
          expandable={{
            expandedRowRender: (run) => (
              <>
                {run.error_message && <Alert type="error" message={run.error_message} />}
                <Typography.Paragraph>
                  指标：
                  {Object.entries(run.metrics)
                    .map(([key, value]) => `${key.replace(/^metrics\//, '')}: ${value.toFixed(4)}`)
                    .join('；') || '暂无'}
                </Typography.Paragraph>
              </>
            ),
          }}
        />
      </Drawer>
      <Drawer
        title={`训练日志 #${selectedRun?.id ?? ''}`}
        open={Boolean(selectedRun)}
        onClose={() => setSelectedRun(undefined)}
        width={1000}
      >
        <Button onClick={() => void logs.refetch()} style={{ marginBottom: 12 }}>
          刷新日志
        </Button>
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12 }}>
          {logs.data || '等待日志输出…'}
        </pre>
      </Drawer>
    </>
  );
}
