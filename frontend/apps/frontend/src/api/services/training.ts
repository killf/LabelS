import type { MetaData } from '../types';
import request from '../request';

export type TrainingStatus = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'INTERRUPTED';

export interface TrainingParameters {
  initial_model: string;
  epochs: number;
  imgsz: number;
  batch: number;
}

export interface TrainingRun {
  id: number;
  task_id: number;
  status: TrainingStatus;
  initial_model: string;
  parameters: TrainingParameters;
  model_name: string | null;
  model_available: boolean;
  log_available: boolean;
  run_id: string | null;
  metrics: Record<string, number>;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export function startTraining(taskId: number, parameters: TrainingParameters) {
  return request.post<never, { data: TrainingRun }>(`/v1/tasks/${taskId}/training-runs`, parameters);
}

export function getTrainingRuns(taskId: number, page = 0, size = 10) {
  return request.get<never, { data: TrainingRun[]; meta_data: MetaData }>(`/v1/tasks/${taskId}/training-runs`, {
    params: { page, size },
  });
}

export function getTrainingLog(taskId: number, runId: number) {
  return request.get<never, string>(`/v1/tasks/${taskId}/training-runs/${runId}/log`, { responseType: 'text' });
}

export function clearTrainingLogs(taskId: number, runId: number) {
  return request.delete(`/v1/tasks/${taskId}/training-runs/${runId}/log`);
}

export function deleteTrainingRun(taskId: number, runId: number) {
  return request.delete(`/v1/tasks/${taskId}/training-runs/${runId}`);
}

export async function downloadModel(taskId: number, name: string) {
  const blob = await request.get<never, Blob>(`/v1/tasks/${taskId}/models/${encodeURIComponent(name)}`, {
    responseType: 'blob',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
