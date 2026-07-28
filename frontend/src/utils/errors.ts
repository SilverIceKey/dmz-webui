interface ValidationDetail {
  loc?: unknown[];
  msg?: unknown;
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: ValidationDetail) => {
        if (!item || typeof item.msg !== 'string') return null;
        const location = Array.isArray(item.loc)
          ? item.loc
            .filter((part) => part !== 'body')
            .map(String)
            .join('.')
          : '';
        const message = item.msg.replace(/^Value error,\s*/i, '');
        return location ? `${location}: ${message}` : message;
      })
      .filter((message): message is string => !!message);
    return messages.length ? messages.join('; ') : null;
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail);
    } catch {
      return null;
    }
  }
  return null;
}

export function formatApiError(error: unknown, fallback = '请求失败'): string {
  if (!error || typeof error !== 'object') return fallback;

  const candidate = error as {
    message?: unknown;
    response?: { data?: { detail?: unknown } };
  };
  const detail = formatDetail(candidate.response?.data?.detail);
  if (detail) return detail;
  if (typeof candidate.message === 'string' && candidate.message) {
    return candidate.message;
  }
  return fallback;
}
