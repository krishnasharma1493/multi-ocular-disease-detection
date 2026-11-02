// Memory first, sessionStorage as backup so a page reload doesn't sign you out.
// sessionStorage is per tab and cleared when the tab closes.
const KEY = 'retinascreen_access_token';
let memory: string | null = null;

export const tokenStore = {
  get: (): string | null => {
    if (memory) return memory;
    try {
      memory = sessionStorage.getItem(KEY);
    } catch {
      memory = null;
    }
    return memory;
  },
  set: (token: string) => {
    memory = token;
    try {
      sessionStorage.setItem(KEY, token);
    } catch {
      /* storage blocked — memory still works */
    }
  },
  clear: () => {
    memory = null;
    try {
      sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  },
};
