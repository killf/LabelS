import { useContext } from 'react';
import { Button, Form, Select } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { FlexLayout } from '@labels/components-react';

import { getProjectModels } from '@/api/services/project';

import { ProjectCreationContext } from '../../projectCreation.context';

export default function ModelConfig() {
  const { modelFormInstance, project } = useContext(ProjectCreationContext);
  const models = useQuery({
    queryKey: ['projectModels', project?.id],
    queryFn: () => getProjectModels(project.id!),
    enabled: Boolean(project?.id),
  });

  return (
    <FlexLayout flex="column" padding="1.5rem" gap="1rem" style={{ maxWidth: 820, margin: '0 auto', width: '100%' }}>
      <h2>模型设置</h2>
      <Form form={modelFormInstance} layout="vertical" initialValues={{ ai_algorithm: 'yolo' }}>
        <Form.Item name="ai_algorithm" label="AI 自动标注算法" rules={[{ required: true }]}>
          <Select options={[{ value: 'yolo', label: 'YOLO 目标检测' }]} />
        </Form.Item>
        <Form.Item
          label="AI 标注模型"
          htmlFor="ai_model_name"
          tooltip="只显示当前项目可用的模型。未选择模型时，可继续人工标注。"
        >
          <FlexLayout items="center" gap=".5rem">
            <Form.Item name="ai_model_name" noStyle>
              <Select
                allowClear
                placeholder="选择模型"
                style={{ flex: 1, minWidth: 0 }}
                loading={models.isFetching}
                options={models.data?.data.map((name) => ({ value: name, label: name }))}
                onDropdownVisibleChange={(open) => {
                  if (open) void models.refetch();
                }}
              />
            </Form.Item>
            <Button loading={models.isFetching} onClick={() => void models.refetch()}>
              刷新
            </Button>
          </FlexLayout>
        </Form.Item>
      </Form>
    </FlexLayout>
  );
}
