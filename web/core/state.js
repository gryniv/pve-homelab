// The menu's shared state: who is signed in, their settings, and what the dashboard shows.
export const st = {
  pub: null, me: null, prefs: null, admin: false, screen: null,
  selUser: null, services: [], guests: [], systems: [],
  wx: null, wxKey: '', wxAt: 0, lastInput: Date.now(), timers: [], loginLang: null, filter: '', sysView: [],
};
