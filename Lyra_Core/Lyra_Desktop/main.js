const { app, BrowserWindow } = require('electron');
const path = require('path');

// A Lyra roda dentro do cerebro_maestro.py (:8000, mesmo host que serve /ui) —
// esta janela é só uma casca desktop pro front-end v2, sem servidor próprio.
const LYRA_UI_URL = 'http://127.0.0.1:8000/ui/';

if (!app.requestSingleInstanceLock()) {
  app.quit();
}

app.on('second-instance', () => {
  const win = BrowserWindow.getAllWindows()[0];
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 720,
    minHeight: 480,
    title: 'Lyra',
    icon: path.join(__dirname, 'lyra.ico'),
    backgroundColor: '#000000',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Nunca abre navegador externo (Ring 0) — qualquer target="_blank"/window.open
  // fica confinado aqui dentro, negado.
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  function load() {
    win.loadURL(LYRA_UI_URL).catch(() => {
      setTimeout(load, 1500);
    });
  }
  load();

  win.webContents.on('did-fail-load', () => {
    setTimeout(load, 1500);
  });
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
