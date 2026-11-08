"""Only the basic per-match metrics supported by Studio's statistics panel."""
CATALOG = [dict(key=k,label=n,unit='',aggregate='sum',group='Básicas') for k,n in [
 ('Score','Puntos'),('Goals','Goles'),('Assists','Asistencias'),('Shots','Tiros'),
 ('Saves','Salvadas'),('Touches','Toques de balón'),('CarTouches','Contactos entre coches'),
 ('Demos','Demoliciones'),('BoostUsed','Turbo usado')]]
DEFAULT_METRICS = ['Score','Goals','Assists','Shots','Saves','BoostUsed']
def normalize_metrics(selected):
    keys = {m['key'] for m in CATALOG}
    if not isinstance(selected,list) or not 1 <= len(selected) <= 6 or len(set(selected)) != len(selected) or any(k not in keys for k in selected):
        raise ValueError('Elige entre 1 y 6 estadísticas básicas, sin repetir.')
    return list(selected)
