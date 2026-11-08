import request from '../request';
import type { ListByApiV1TasksTaskIdSamplesGetParams, PreAnnotationListResponse } from '../types';

export async function getPreAnnotations({
  task_id,
  ...params
}: ListByApiV1TasksTaskIdSamplesGetParams & {
  sample_name?: string;
}): Promise<PreAnnotationListResponse> {
  return await request.get(`/v1/tasks/${task_id}/pre_annotations`, {
    params: {
      ...params,
      page: typeof params.page === 'undefined' ? 0 : params.page - 1,
    },
  });
}
