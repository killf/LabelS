import { useContext } from 'react';
import { Alert, Button, Form, Select } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { FlexLayout } from '@labels/components-react';

import { getTaskModels } from '@/api/services/task';
import { downloadModel } from '@/api/services/training';

import { TaskCreationContext } from '../../taskCreation.context';

export default function ModelConfig() {
  const { modelFormInstance, task } = useContext(TaskCreationContext);
  const selectedModel = Form.useWatch('ai_model_name', modelFormInstance) as string | undefined;
  const models = useQuery({
    queryKey: ['taskModels', task?.id],
    queryFn: () => getTaskModels(task.id!),
    enabled: Boolean(task?.id),
  });

  return (
    <FlexLayout flex="column" padding="1.5rem" gap="1rem" style={{ maxWidth: 820, margin: '0 auto', width: '100%' }}>
      <h2>模型设置</h2>
      <Alert
        type="info"
        showIcon
        message="可以先完成图片标注，在任务页发起训练，再选择训练产出的模型用于 AI 辅助标注。"
      />
      <Form form={modelFormInstance} layout="vertical" initialValues={{ ai_algorithm: 'yolo' }}>
        <Form.Item name="ai_algorithm" label="AI 自动标注算法" rules={[{ required: true }]}>
          <Select options={[{ value: 'yolo', label: 'YOLO 目标检测' }]} />
        </Form.Item>
        <Form.Item
          name="ai_model_name"
          label="AI 标注模型"
          extra="只显示当前任务可用的模型。未选择模型时，可继续人工标注。"
        >
          <Select
            allowClear
            placeholder="选择模型"
            loading={models.isFetching}
            options={models.data?.data.map((name) => ({ value: name, label: name }))}
            onDropdownVisibleChange={(open) => {
              if (open) void models.refetch();
            }}
          />
        </Form.Item>
      </Form>
      <Button style={{ alignSelf: 'flex-start' }} onClick={() => void models.refetch()}>
        刷新模型列表
      </Button>
      <Button
        style={{ alignSelf: 'flex-start' }}
        disabled={!selectedModel}
        onClick={() => {
          if (selectedModel) void downloadModel(task.id!, selectedModel);
        }}
      >
        下载选中模型
      </Button>
    </FlexLayout>
  );
}
