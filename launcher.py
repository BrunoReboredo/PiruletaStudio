"""Portable entrypoint with visible startup errors and a local diagnostic log."""
import traceback
from pathlib import Path
import sys

if __name__ == '__main__':
    try:
        from app import App, tk
        root = tk.Tk()
        app = App(root)
        root.mainloop()
    except Exception:
        folder = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
        (folder/'inicio.log').write_text('Piruleta Studio 0.8.1\n'+traceback.format_exc(), encoding='utf-8')
        from tkinter import messagebox
        messagebox.showerror('Piruleta Studio', 'No se pudo iniciar. Revisa inicio.log junto al ejecutable.')
        raise
