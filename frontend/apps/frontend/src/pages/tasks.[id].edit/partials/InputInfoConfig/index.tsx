import React, { memo, useContext } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Form, Input, Select } from 'antd';
import styled from 'styled-components';
import { FlexLayout } from '@labelu/components-react';
import { useTranslation } from '@labelu/i18n';

import { MediaType } from '@/api/types';
import { getDataSources } from '@/api/services/datasource';
import { getTaskModels } from '@/api/services/task';

import { TaskCreationContext } from '../../taskCreation.context';

const Inner = styled(FlexLayout)`
  width: 740px;
  margin: auto;
`;

const InputInfoConfig = () => {
  const { basicFormInstance, task } = useContext(TaskCreationContext);
  const { t } = useTranslation();
  const { data: models, refetch: refreshModels } = useQuery({
    queryKey: ['taskModels', task?.id],
    queryFn: () => getTaskModels(task.id!),
    enabled: Boolean(task?.id),
  });
  const { data: sources } = useQuery({
    queryKey: ['datasetDataSources'],
    queryFn: () => getDataSources({ size: 100 }),
  });

  return (
    <FlexLayout padding="1rem" flex="column">
      <Inner flex="column">
        <h2>{t('basicConfig')}</h2>
        <FlexLayout.Content>
          <Form form={basicFormInstance} labelCol={{ span: 3 }} wrapperCol={{ span: 21 }}>
            <Form.Item
              label={t('taskName')}
              name="name"
              required
              rules={[{ required: true, message: t('taskNameRequired') }]}
            >
              <Input placeholder={t('taskName50CharactersPlease')} maxLength={50} />
            </Form.Item>
            <Form.Item
              label={t('mediaType')}
              name="media_type"
              rules={[{ required: true, message: t('mediaTypeRequired') }]}
            >
              <Select
                placeholder={t('selectMediaTypePlease')}
                options={[
                  {
                    label: t('image'),
                    value: MediaType.IMAGE,
                  },
                ]}
              />
            </Form.Item>
            <Form.Item
              label="数据集数据源"
              name="dataset_data_source_id"
              rules={[{ required: true, message: '请选择保存 YOLO 数据集的 S3 数据源' }]}
              extra={<Link to="/datasources">管理 S3 数据源</Link>}
            >
              <Select
                placeholder="选择 S3 数据源"
                options={sources?.data.map((source) => ({ value: source.id, label: source.name }))}
              />
            </Form.Item>
            <Form.Item
              label="数据集目录"
              name="dataset_prefix"
              extra="相对于数据源前缀。每个任务使用独立目录，标注保存后自动同步标准 YOLO 数据集。"
            >
              <Input placeholder="例如 dataset/ego-quality" />
            </Form.Item>
            <Form.Item
              label="AI 模型"
              name="ai_model_name"
              extra="从当前数据集 models/ 目录选择权重。任务创建后可刷新列表。"
            >
              <Select
                allowClear
                placeholder="选择 YOLO 权重"
                disabled={!task?.id}
                options={models?.data.map((name) => ({ value: name, label: name }))}
                onDropdownVisibleChange={(open) => {
                  if (open) refreshModels();
                }}
              />
            </Form.Item>
            <Form.Item label={t('taskDescription')} name="description">
              <Input.TextArea placeholder={t('taskDescription500CharactersPlease')} maxLength={500} rows={6} />
            </Form.Item>
            <Form.Item label={t('taskTip')} name="tips">
              <Input.TextArea placeholder={t('taskTipPlaceholder')} maxLength={1000} rows={6} />
            </Form.Item>
          </Form>
        </FlexLayout.Content>
      </Inner>
    </FlexLayout>
  );
};
export default memo(InputInfoConfig);
