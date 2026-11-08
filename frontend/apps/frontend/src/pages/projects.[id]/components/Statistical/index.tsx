import { SettingOutlined } from '@ant-design/icons';
import { useNavigate, useRouteLoaderData } from 'react-router';
import { Button } from 'antd';
import _ from 'lodash-es';
import styled from 'styled-components';
import { FlexLayout } from '@labels/components-react';
import { useTranslation } from '@labels/i18n';

import type { ProjectLoaderResult } from '@/loaders/project.loader';
import useMe from '@/hooks/useMe';

import commonController from '../../../../utils/common';

const Circle = styled.div<{
  color: string;
}>`
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background-color: ${({ color }) => color};
`;

export interface ProjectStatusProps {
  status?: 'done' | 'new' | 'skipped';
  count?: number;
}

export function ProjectStatus({ children, status, count }: React.PropsWithChildren<ProjectStatusProps>) {
  const { t } = useTranslation();
  const colorMapping = {
    done: 'var(--color-primary)',
    new: 'var(--color-text-tertiary)',
    skipped: 'var(--orange)',
  };

  const textMapping = {
    done: t('annotated'),
    new: t('new'),
    skipped: t('skipped'),
  };

  const color = status ? colorMapping[status] : colorMapping.new;
  const title = status ? textMapping[status] : children;

  return (
    <FlexLayout items="center" gap=".5rem">
      {status && <Circle color={color} />}
      <b>{title}</b>
      {count && <b>{count}</b>}
    </FlexLayout>
  );
}

const Statistical = ({ children }: React.PropsWithChildren) => {
  const routerLoaderData = useRouteLoaderData('project') as ProjectLoaderResult;
  const projectData = routerLoaderData.project;
  const { stats = {} } = projectData || {};
  const projectId = _.get(projectData, 'id');
  const { t } = useTranslation();
  const me = useMe();
  const isMeTheCreator = projectData?.created_by?.id === me.data?.id;

  const samples = routerLoaderData.samples;

  const navigate = useNavigate();

  const handleGoAnnotation = () => {
    if (!samples || samples.data.length === 0) {
      return;
    }

    navigate(`/projects/${projectId}/samples/${samples.data[0].id}`);
  };
  const handleGoConfig = () => {
    navigate(`/projects/${projectId}/edit#config`);
  };
  const handleGoUpload = () => {
    navigate(`/projects/${projectId}/edit#upload`);
  };

  return (
    <FlexLayout justify="space-between" items="center">
      <FlexLayout items="center" gap="3rem">
        <b>{t('dataOverview')}</b>
        <ProjectStatus status="done" count={stats.done} />
        <ProjectStatus status="new" count={stats.new} />
        <ProjectStatus status="skipped" count={stats.skipped} />
        <ProjectStatus count={stats.done! + stats.new! + stats.skipped!}>{t('total')}</ProjectStatus>
      </FlexLayout>
      <FlexLayout gap=".5rem">
        {isMeTheCreator && (
          <Button type="text" icon={<SettingOutlined />} onClick={handleGoConfig}>
            {t('projectConfig')}
          </Button>
        )}
        <Button type="primary" ghost onClick={handleGoUpload}>
          {t('uploadData')}
        </Button>
        <Button type="primary" onClick={commonController.debounce(handleGoAnnotation, 100)}>
          {t('startAnnotate')}
        </Button>
        {children}
      </FlexLayout>
    </FlexLayout>
  );
};
export default Statistical;
