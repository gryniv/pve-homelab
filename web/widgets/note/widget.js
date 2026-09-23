// Нотатка: власний текст користувача, редагується в налаштуваннях (Макет і віджети).
export default {
  title: 'Нотатка',
  zones: ['side'],
  render(_d, { ui, app }) {
    const text = app.prefs().note || 'Порожньо. Текст задається в налаштуваннях, розділ «Макет і віджети».';
    return `<h4>Нотатка</h4><div style="font-size:.9em;line-height:1.5;white-space:pre-wrap">${ui.esc(text)}</div>`;
  },
};
