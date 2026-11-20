"""Portable entrypoint with visible startup errors and a local diagnostic log."""
import os
import traceback
from pathlib import Path
import sys

def run_app():
    from app import App, tk
    App(tk.Tk()).root.mainloop()


def main():
    if os.name != 'nt':
        run_app()
        return

    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create_mutex = kernel.CreateMutexW
    create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    create_mutex.restype = wintypes.HANDLE
    close_handle = kernel.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_mutex(None, False, r'Local\PiruletaStudio')
    already_running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if already_running:
            from tkinter import Tk, messagebox
            root = Tk()
            root.withdraw()
            messagebox.showinfo('Piruleta Studio', 'La aplicación ya está abierta. Usa esa ventana para aplicar los cambios.', parent=root)
            root.destroy()
            return
        run_app()
    finally:
        close_handle(handle)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        folder = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
        (folder/'inicio.log').write_text('Piruleta Studio 0.8.5\n'+traceback.format_exc(), encoding='utf-8')
        from tkinter import messagebox
        messagebox.showerror('Piruleta Studio', 'No se pudo iniciar. Revisa inicio.log junto al ejecutable.')
        raise
