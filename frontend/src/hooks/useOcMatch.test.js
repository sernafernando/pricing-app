import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useOcMatch, {
  needsOcMatchPoll,
  OC_MATCH_BASE,
  OC_MATCH_POLL_MS,
} from './useOcMatch';
import api from '../services/api';

function job(overrides = {}) {
  return {
    id: 1,
    pedido_id: 10,
    attachment_id: 20,
    status: 'queued',
    error_message: null,
    acta: null,
    excel_rel_path: null,
    started_at: null,
    finished_at: null,
    created_at: '2026-09-19T10:00:00Z',
    updated_at: '2026-09-19T10:00:00Z',
    retryable: false,
    ...overrides,
  };
}

function listPayload(items) {
  return { items, total: items.length, page: 1, page_size: 50 };
}

describe('needsOcMatchPoll', () => {
  it('is true when a list job is queued or running', () => {
    expect(needsOcMatchPoll([job({ status: 'queued' })], null)).toBe(true);
    expect(needsOcMatchPoll([job({ status: 'running' })], null)).toBe(true);
  });

  it('is true when the selected job is still active', () => {
    expect(needsOcMatchPoll([job({ status: 'done' })], job({ status: 'running' }))).toBe(
      true,
    );
  });

  it('is false when list and selected are terminal', () => {
    expect(needsOcMatchPoll([job({ status: 'done' })], job({ status: 'error' }))).toBe(
      false,
    );
    expect(needsOcMatchPoll([job({ status: 'skipped' })], null)).toBe(false);
  });
});

describe('useOcMatch', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.get.mockReset();
    api.post.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('lists jobs with page and optional status', async () => {
    api.get.mockResolvedValue({ data: listPayload([job()]) });
    const { result } = renderHook(() => useOcMatch({ status: 'error', page: 2 }));

    await waitFor(() => expect(result.current.jobs).toHaveLength(1));
    expect(api.get).toHaveBeenCalledWith(OC_MATCH_BASE, {
      params: { page: 2, page_size: 50, status: 'error' },
    });
  });

  it('loads detail when a job is selected', async () => {
    api.get.mockImplementation((url) => {
      if (url === `${OC_MATCH_BASE}/1`) {
        return Promise.resolve({ data: { ...job({ status: 'done' }), renglones: [] } });
      }
      return Promise.resolve({ data: listPayload([job({ status: 'done' })]) });
    });

    const { result } = renderHook(() => useOcMatch());
    await waitFor(() => expect(result.current.jobs).toHaveLength(1));

    await act(async () => {
      result.current.setSelectedId(1);
    });

    await waitFor(() => expect(result.current.selected?.id).toBe(1));
    expect(api.get).toHaveBeenCalledWith(`${OC_MATCH_BASE}/1`);
  });

  it('retries a job', async () => {
    api.get.mockResolvedValue({ data: listPayload([job({ status: 'error', retryable: true })]) });
    api.post.mockResolvedValue({ data: job({ status: 'queued' }) });

    const { result } = renderHook(() => useOcMatch());
    await waitFor(() => expect(result.current.jobs).toHaveLength(1));

    await act(async () => {
      await result.current.retry(1);
    });

    expect(api.post).toHaveBeenCalledWith(`${OC_MATCH_BASE}/1/retry`, {
      refrescar_doc_refs: false,
    });
    expect(result.current.jobs[0].status).toBe('queued');
  });

  it('retries a job with refrescar_doc_refs', async () => {
    api.get.mockResolvedValue({ data: listPayload([job({ status: 'error', retryable: true })]) });
    api.post.mockResolvedValue({ data: job({ status: 'queued' }) });

    const { result } = renderHook(() => useOcMatch());
    await waitFor(() => expect(result.current.jobs).toHaveLength(1));

    await act(async () => {
      await result.current.retry(1, { refrescar_doc_refs: true });
    });

    expect(api.post).toHaveBeenCalledWith(`${OC_MATCH_BASE}/1/retry`, {
      refrescar_doc_refs: true,
    });
  });

  it('refreshDocRefs posts empty body to refresh-doc-refs', async () => {
    api.get.mockResolvedValue({ data: listPayload([job({ status: 'done' })]) });
    api.post.mockResolvedValue({ data: job({ status: 'done' }) });

    const { result } = renderHook(() => useOcMatch());
    await waitFor(() => expect(result.current.jobs).toHaveLength(1));

    await act(async () => {
      await result.current.refreshDocRefs(1);
    });

    expect(api.post).toHaveBeenCalledWith(`${OC_MATCH_BASE}/1/refresh-doc-refs`);
    expect(result.current.jobs[0].status).toBe('done');
    expect(needsOcMatchPoll(result.current.jobs, result.current.selected)).toBe(false);
  });

  it('does not poll done or error after refreshDocRefs', async () => {
    api.get.mockResolvedValue({ data: listPayload([job({ status: 'error', retryable: true })]) });
    api.post.mockResolvedValue({ data: job({ status: 'error', retryable: true }) });

    const { result } = renderHook(() => useOcMatch());
    await waitFor(() => expect(result.current.jobs).toHaveLength(1));

    await act(async () => {
      result.current.setSelectedId(1);
    });
    await act(async () => {
      await result.current.refreshDocRefs(1);
    });

    expect(needsOcMatchPoll(result.current.jobs, result.current.selected)).toBe(false);
    const callsAfter = api.get.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OC_MATCH_POLL_MS * 2);
    });
    expect(api.get.mock.calls.length).toBe(callsAfter);
  });

  it('downloads excel as a blob', async () => {
    const blob = new Blob(['xlsx'], { type: 'application/vnd.ms-excel' });
    api.get.mockImplementation((url, config) => {
      if (url === `${OC_MATCH_BASE}/1/excel`) {
        expect(config).toEqual({ responseType: 'blob' });
        return Promise.resolve({ data: blob });
      }
      return Promise.resolve({ data: listPayload([job({ status: 'done' })]) });
    });

    const createObjectURL = vi.fn(() => 'blob:oc-match');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });

    const { result } = renderHook(() => useOcMatch());
    await waitFor(() => expect(result.current.jobs).toHaveLength(1));

    await act(async () => {
      const downloaded = await result.current.downloadExcel(1);
      expect(downloaded).toBe(blob);
    });

    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:oc-match');
    vi.unstubAllGlobals();
  });

  it('stops polling when status becomes terminal', async () => {
    api.get.mockResolvedValue({ data: listPayload([job({ status: 'queued' })]) });
    const { result } = renderHook(() => useOcMatch());
    await waitFor(() => expect(result.current.jobs[0]?.status).toBe('queued'));

    api.get.mockResolvedValue({ data: listPayload([job({ status: 'done' })]) });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OC_MATCH_POLL_MS);
    });
    await waitFor(() => expect(result.current.jobs[0]?.status).toBe('done'));

    const callsAfterDone = api.get.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OC_MATCH_POLL_MS * 2);
    });
    expect(api.get.mock.calls.length).toBe(callsAfterDone);
  });

  it('clears the poll interval on unmount', async () => {
    api.get.mockResolvedValue({ data: listPayload([job({ status: 'running' })]) });
    const { unmount } = renderHook(() => useOcMatch());
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    const callsAtUnmount = api.get.mock.calls.length;
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(OC_MATCH_POLL_MS * 2);
    });
    expect(api.get.mock.calls.length).toBe(callsAtUnmount);
  });
});
