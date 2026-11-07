import request from '../request';
import {
  type AutoLabelJobResponse,
  type DeleteApiV1TasksTaskIdDeleteParams,
  type DeleteSampleCommand,
  type GetApiV1TasksTaskIdSamplesSampleIdGetParams,
  type GetPreApiV1TasksTaskIdSamplesSampleIdPreGetParams,
  type ListByApiV1TasksTaskIdSamplesGetParams,
  type OkRespCommonDataResp,
  type OkRespCreateSampleResponse,
  type OkRespAutoLabelResponse,
  type OkRespSampleResponse,
  type PatchSampleCommand,
  type SampleData,
  type SampleListResponse,
  type SampleResponse,
  type UpdateApiV1TasksTaskIdSamplesSampleIdPatchParams,
} from '../types';

export async function createSamples(
  taskId: number,
  data: {
    file_id: number;
    data: SampleData;
  }[],
): Promise<OkRespCreateSampleResponse> {
  return await request.post(`/v1/tasks/${taskId}/samples`, data);
}

export async function getSamples({
  task_id,
  ...params
}: ListByApiV1TasksTaskIdSamplesGetParams): Promise<SampleListResponse> {
  return await request.get(`/v1/tasks/${task_id}/samples`, {
    params: {
      ...params,
      page: typeof params.page === 'undefined' ? 0 : params.page - 1,
    },
  });
}

export async function getSample({
  task_id,
  sample_id,
}: GetApiV1TasksTaskIdSamplesSampleIdGetParams): Promise<OkRespSampleResponse> {
  return await request.get(`/v1/tasks/${task_id}/samples/${sample_id}`);
}

export async function updateSampleState(
  { task_id, sample_id, ...params }: UpdateApiV1TasksTaskIdSamplesSampleIdPatchParams,
  body: PatchSampleCommand,
): Promise<SampleResponse> {
  return await request.patch(`/v1/tasks/${task_id}/samples/${sample_id}`, body, {
    params: {
      sample_id,
      ...params,
    },
  });
}

export async function updateSampleAnnotationResult(
  taskId: number,
  sampleId: number,
  data: SampleResponse,
): Promise<SampleResponse> {
  return await request.patch(
    `/v1/tasks/${taskId}/samples/${sampleId}`,
    {
      data: data.data,
      state: data.state,
      annotated_count: data.annotated_count,
    },
    {
      params: {
        sample_id: sampleId,
      },
    },
  );
}

export async function autoLabelSample(taskId: number, sampleId: number): Promise<OkRespAutoLabelResponse> {
  return await request.post(`/v1/tasks/${taskId}/samples/${sampleId}/auto_label`, undefined, {
    timeout: 5 * 60 * 1000,
    params: {
      sample_id: sampleId,
    },
  });
}

export async function createAutoLabelJob(taskId: number): Promise<{ data: AutoLabelJobResponse }> {
  return await request.post(`/v1/tasks/${taskId}/auto_label_job`);
}

export async function getAutoLabelJobStatus(taskId: number, jobId: number): Promise<{ data: AutoLabelJobResponse }> {
  return await request.get(`/v1/tasks/${taskId}/auto_label_job/${jobId}`);
}

export async function deleteSamples(
  { task_id }: DeleteApiV1TasksTaskIdDeleteParams,
  body: DeleteSampleCommand,
): Promise<OkRespCommonDataResp> {
  return await request.delete(`/v1/tasks/${task_id}/samples`, {
    data: body,
  });
}

export async function getPreSample({
  sample_id,
  task_id,
}: GetPreApiV1TasksTaskIdSamplesSampleIdPreGetParams): Promise<OkRespSampleResponse> {
  return await request.get(`/v1/tasks/${task_id}/samples/${sample_id}/pre`);
}
