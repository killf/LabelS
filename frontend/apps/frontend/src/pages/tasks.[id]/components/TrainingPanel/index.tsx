import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Drawer,
  Form,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { useNavigate } from 'react-router-dom';

import { getTaskModels } from '@/api/services/task';
import {
  clearTrainingLogs,
  deleteTrainingRun,
  downloadModel,
  getTrainingLog,
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

export default function TrainingPanel({ taskId, canClean }: { taskId: number; canClean: boolean }) {
  const [showStart, setShowStart] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [selectedRun, setSelectedRun] = useState<TrainingRun>();
  const [page, setPage] = useState(1);
  const [cleaning, setCleaning] = useState<number>();
  const [form] = Form.useForm<TrainingParameters>();
  const navigate = useNavigate();
  const runs = useQuery({
    queryKey: ['trainingRuns', taskId, page],
    queryFn: () => getTrainingRuns(taskId, page - 1),
    refetchInterval: (query) => (query.state.data?.data.some((run) => active(run.status)) ? 2000 : false),
  });
  const models = useQuery({
    queryKey: ['taskModels', taskId],
    queryFn: () => getTaskModels(taskId),
    enabled: showStart,
  });
  const logs = useQuery({
    queryKey: ['trainingLog', taskId, selectedRun?.id],
    queryFn: () => getTrainingLog(taskId, selectedRun!.id),
    enabled: Boolean(selectedRun),
    refetchInterval: () =>
      runs.data?.data.some((run) => run.id === selectedRun?.id && active(run.status)) ? 2000 : false,
  });
  const start = useMutation({
    mutationFn: (values: TrainingParameters) => startTraining(taskId, values),
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
      if (includeModel) await deleteTrainingRun(taskId, run.id);
      else await clearTrainingLogs(taskId, run.id);
      if (selectedRun?.id === run.id) setSelectedRun(undefined);
      message.success(includeModel ? '执行记录、模型和日志已清理' : '日志已清理，执行记录和模型已保留');
      await runs.refetch();
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
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="训练集和测试集都需要已完成标注的图片。测试集同时用于每轮验证和选择最优模型。"
        />
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => start.mutate(values)}
          initialValues={{ initial_model: 'yolo26s.pt', epochs: 100, imgsz: 1024, batch: 2 }}
        >
          <Form.Item name="initial_model" label="初始模型" rules={[{ required: true }]}>
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
                  label: '本任务模型',
                  options: (models.data?.data ?? []).map((name) => ({ value: name, label: name })),
                },
              ]}
            />
          </Form.Item>
          <Form.Item name="epochs" label="训练轮数" rules={[{ required: true }]}>
            <InputNumber min={1} max={10000} precision={0} />
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
            <InputNumber min={32} max={4096} step={32} precision={0} />
          </Form.Item>
          <Form.Item
            name="batch"
            label="每批图片数"
            extra="-1 表示自动选择"
            rules={[
              { required: true },
              {
                validator: (_, value) =>
                  value === -1 || value > 0 ? Promise.resolve() : Promise.reject(new Error('请输入 -1 或正整数')),
              },
            ]}
          >
            <InputNumber min={-1} max={1024} precision={0} />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer title="训练记录" open={showHistory} onClose={() => setShowHistory(false)} width={1080}>
        <Alert
          type="info"
          showIcon
          message="测试集同时参与验证和选模，因此这里的指标不代表独立测试成绩。"
          style={{ marginBottom: 16 }}
        />
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
            { title: '初始模型', dataIndex: 'initial_model' },
            {
              title: '参数',
              render: (_, run) =>
                `${run.parameters.epochs} 轮 / ${run.parameters.imgsz}px / batch ${run.parameters.batch}`,
            },
            { title: '开始时间', render: (_, run) => time(run.started_at) },
            { title: '结束时间', render: (_, run) => time(run.finished_at) },
            { title: '产出模型', render: (_, run) => run.model_name ?? '-' },
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
                  <Button
                    type="link"
                    disabled={!run.model_available}
                    onClick={() => {
                      if (run.model_name) void downloadModel(taskId, run.model_name);
                    }}
                  >
                    下载模型
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
                    title="清理此记录、产出模型和全部日志？此操作不可恢复。"
                    onConfirm={() => cleanup(run, true)}
                  >
                    <Button type="link" danger disabled={!canClean || active(run.status) || cleaning === run.id}>
                      清理记录
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
                    .map(([key, value]) => `${key}: ${value.toFixed(4)}`)
                    .join('；') || '暂无'}
                </Typography.Paragraph>
                {run.status === 'SUCCEEDED' && (
                  <Button
                    onClick={() => {
                      setShowHistory(false);
                      navigate(`/tasks/${taskId}/edit#model`);
                    }}
                  >
                    前往模型设置
                  </Button>
                )}
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
