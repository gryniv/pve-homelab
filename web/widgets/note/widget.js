// Note: the user's own text, edited in Settings → Layout & widgets.
export default {
  i18n: {
    uk: { title: 'Нотатка', empty: 'Порожньо. Текст задається в налаштуваннях, розділ «Макет і віджети».' },
    en: { title: 'Note', empty: 'Empty. Set the text in Settings → Layout & widgets.' },
  },
  zones: ['side'],
  render(_d, { ui, app, t }) {
    const text = app.prefs().note || t('empty');
    return `<h4>${t('title')}</h4><div style="font-size:.9em;line-height:1.5;white-space:pre-wrap">${ui.esc(text)}</div>`;
  },
};
