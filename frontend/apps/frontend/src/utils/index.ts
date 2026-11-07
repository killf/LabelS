export { default as compare } from 'lodash/isEqual.js';

/** 读取 JSON，仅还原 jsonStringify 保存的 /pattern/flags 正则字符串。 */
export const jsonParse = <T = any>(value: string): T => {
  return JSON.parse(value, (_key: string, entry: unknown) => {
    if (typeof entry !== 'string') {
      return entry;
    }

    try {
      const decoded = decodeURIComponent(entry);
      const separator = decoded.lastIndexOf('/');
      if (decoded.startsWith('/') && separator > 0) {
        return new RegExp(decoded.slice(1, separator), decoded.slice(separator + 1));
      }
    } catch {
      // 普通文本、损坏的编码及无效正则均保留原值。
    }

    return entry;
  });
};

/** 序列化配置，将 RegExp 编码为可由 jsonParse 还原的字符串。 */
export const jsonStringify = (value: Record<string, unknown>, type = 2): string => {
  return JSON.stringify(
    value,
    (_key: string, v: unknown) => {
      if (v instanceof RegExp) {
        return encodeURIComponent(v.toString());
      }
      return v;
    },
    type,
  );
};

export function downloadFromUrl(url: string, name?: string) {
  const link = document.createElement('a');
  link.href = url;

  if (name) {
    link.setAttribute('download', name);
  }

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export function getThumbnailUrl(url: string) {
  return url.replace(/(.*)(\..*)$/, '$1-thumbnail$2');
}
