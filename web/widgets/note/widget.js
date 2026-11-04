// Note: the user's own text (widget settings; older setups kept it in prefs.note).
export default {
  zones: ['side'],
  options: [
    { key: 'head', type: 'text', label: 'opt_head', default: '' },
    { key: 'text', type: 'textarea', label: 'opt_text', default: '' },
  ],
  render(_d, { ui, app, t, opts }) {
    const text = opts.text || app.prefs().note || t('empty');
    return `<h4>${ui.esc(opts.head || t('title'))}</h4><div style="font-size:.9em;line-height:1.5;white-space:pre-wrap">${ui.esc(text)}</div>`;
  },
};
