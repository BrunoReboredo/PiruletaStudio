# Piruleta Studio

Aplicación de escritorio para Windows que reúne Animaciones, Overlay y Estadísticas con un estado compartido, una conexión TCP a Rocket League y control de escenas de OBS Studio.

## Abrir

La actualización de esta entrega está en **portable/Piruleta Studio 0.7/Piruleta Studio.exe**. Las versiones anteriores se conservan en sus carpetas para no interrumpir trabajos en curso. Abre el ejecutable con doble clic y conserva `_internal` a su lado. No necesita Python instalado. Las compilaciones de desarrollo con `build.ps1` se crean en `portable/Piruleta Studio/`.

Para ejecutar el código fuente, con Python 3.11 o posterior (incluido Tkinter), abre **Abrir Piruleta Studio.cmd**. No necesita paquetes de pip. También puedes ejecutar `python app.py` desde esta carpeta.

Puedes generar los vídeos con **Blender 4.4 o posterior**, o cargar tus propios vídeos sin instalar Blender. Para conectar OBS basta con una única URL de fuente de navegador; no necesita WebSocket ni contraseña. El control de escenas por WebSocket se conserva como opción adicional.

## Preparar una serie

1. Introduce nombre, abreviatura, logo PNG/JPG de hasta 4 MB, color y coche de cada equipo. Equipo A corresponde al lado azul del juego y B al naranja.
2. Opcionalmente selecciona una calcomanía ZIP o imagen. **Solo Octane, Fennec y Dominus.** Los BodyID del paquete tienen prioridad sobre el nombre de archivo. El coche se selecciona al identificarlo; se rechazan modelos incompatibles. Una imagen sin identificación necesita confirmación manual de compatibilidad; no se puede deducir su mapa UV con certeza y no se convierte entre coches.
3. Elige el BO y pulsa **Continuar al panel**. Se valida y comparte la identidad con todos los elementos. Volver a continuar desde Datos configura una nueva serie y reinicia el resultado; no modifica las tres apps de origen.
4. En **Panel de control → Blender y animaciones**, elige cómo preparar los cuatro vídeos: selecciona **EEVEE** (rápido, predeterminado) o **CYCLES** (calidad), indica Blender y la carpeta de salida y pulsa **Preparar vídeos · generar solo los que faltan**, o selecciona tus cuatro MP4 y pulsa **Usar estos vídeos**. Se reutilizan los vídeos coincidentes de la biblioteca. Si los cuatro ya están guardados se recuperan al continuar desde Datos y se habilita Iniciar serie sin renderizar. Se lee la duración real de cada vídeo. Los renders nuevos pueden tardar según el ordenador; puedes cancelar y consultar el registro junto a los archivos parciales.
5. Pulsa **Copiar URL para OBS**. En tu escena de OBS añade una **Fuente de navegador**, pega la dirección y establece **1920 × 1080**. Desactiva las opciones de cerrar la fuente cuando no esté visible y actualizarla al activarse para conservar la precarga de los vídeos.
6. Coloca esa fuente **encima de la captura de Rocket League**. Puedes mantener la misma escena de OBS durante toda la serie: la URL muestra prepartido, marcador, victoria, estadísticas y cierre automáticamente. Durante el partido el marcador es transparente; las animaciones y las estadísticas ocultan el juego. No necesitas otras fuentes ni contraseña.
7. Abre Vista del programa para revisar el resultado. Pulsa **Iniciar serie** cuando los equipos estén listos y antes del primer partido.

Los vídeos se precargan en la fuente de navegador. Las dos victorias ya están preparadas antes del inicio. La aparición depende de recibir `MatchEnded` y del sondeo del navegador; no hay render al terminar el partido. Todos los controles del panel siguen funcionando con esta única URL. Mantén Piruleta Studio abierto mientras la uses.

### Control opcional de escenas de OBS

Si además quieres cambiar las escenas de OBS, habilita su servidor WebSocket 5 en Herramientas → Ajustes del servidor WebSocket. El puerto predeterminado es 4455. Introduce la contraseña en el apartado opcional del panel; se conserva solo en memoria. **Conectar y preparar escenas** crea seis escenas `Piruleta · …` y una fuente compartida `Piruleta · Programa`. Si ya existen se reutilizan. Coloca la captura del juego debajo de esa fuente en `Piruleta · Partido`. No se inicia ni se detiene la emisión o grabación. Utiliza este modo como alternativa a la fuente añadida manualmente.

## Flujo automático

`Datos → preparación → prepartido → partido → estadísticas (10 s) → siguiente partido`

Al terminar la serie: `partido → victoria completa del ganador → estadísticas (10 s) → fin de serie`.

Los vídeos generados con Blender duran 13 s para prepartido y 4 s para cada victoria. El prepartido incorpora los nuevos acercamientos a ambos coches, el giro rápido y el regreso al plano inicial; la victoria utiliza el nuevo barrido lateral. El identificador interno de la escena sigue siendo `02_VICTORIA_2s` por compatibilidad, aunque ahora dura 4 segundos. Los vídeos propios respetan su duración real. La duración predeterminada de estadísticas sigue siendo 10 s en ambos casos.

La versión 0.4 incorpora el diseño actualizado de PostMatchRocketLeague: estadísticas a pantalla completa, sin márgenes exteriores y con las filas distribuidas por toda la altura. La nueva plantilla de IntroRocketLeague cambia la firma de los vídeos de la biblioteca: pulsa Preparar vídeos para generar los nuevos recorridos en EEVEE o Cycles. Los clips anteriores se conservan, pero no se reutilizan automáticamente para la plantilla nueva. Cargar una preparación antigua o vídeos propios de forma manual sigue mostrando los archivos que hayas elegido.

Se admiten BO1, BO2, BO3, BO4, BO5 y BO7. Los formatos pares pueden acabar empatados; un empate muestra estadísticas y cierre, sin atribuir una victoria de serie a ningún equipo. La serie termina al alcanzar la mayoría de victorias o consumir el BO. No se contabilizan finales recibidos antes de Iniciar serie ni finales repetidos. Sin MatchGuid se usa el ciclo de inicio/final del partido como respaldo.

Las estadísticas se congelan al finalizar el partido; salir al menú o comenzar el siguiente no borra esa captura. Un inicio temprano no interrumpe las escenas en curso. Tras una serie finalizada, configura una nueva desde Datos.

## Categorías del panel de control

### Marcador

Reúne todas las opciones de la aplicación independiente Overlay, dentro de Studio y con una sola conexión al juego:

- **Textos:** torneo, ronda, número de partido, nombres, escudos y cambio de equipos de lado.
- **Diseño:** colores, estilo angular/redondeado/clásico, tipografía, escala, opacidad y posición del marcador.
- **Fondos:** vínculos de los fondos del turbo y de las tarjetas a la paleta del marcador.
- **Elementos:** escudos, jugadores, estadísticas y turbo del jugador observado, marca, avisos y conteo automático de victorias.
- **Posiciones:** coordenadas y escala de jugadores A/B, tarjeta del jugador observado, turbo, marca y avisos.
- **CSS libre** y esquema en directo. La copia de URL y la vista del programa están en la cabecera común del panel; no se repiten dentro de Marcador.
- **Control del partido:** BO, goles recibidos del juego, victorias de serie con botones +/− y reinicio de serie. Guardar y cargar perfiles del marcador, incluidos los de la app independiente.
- Puerto de la Stats API y reconexión. Los goles, reloj y prórroga se reciben automáticamente del juego.

Los colores y casillas se aplican al instante; usa **Aplicar diseño** para textos, posiciones y CSS. **Cambiar equipos de lado** intercambia identidades, colores y victorias; mantiene asociados los vídeos de victoria a su equipo original. La telemetría sigue correspondiendo a los lados azul/naranja del juego.

El diseño del marcador no vuelve a generar las animaciones. Los cambios de nombre/escudo del marcador son independientes de los textos y recursos de los vídeos ya preparados; para cambiar estos últimos, configura la identidad en Datos y genera o carga los nuevos vídeos.

**Reiniciar serie** borra el resultado anterior y mantiene el diseño y los vídeos. Se ha retirado el apartado Control manual de emergencia del marcador, incluidos los botones de final y siguiente partido manual.

### Blender y animaciones

La ruta de Blender, el modo de render y la carpeta donde guardar las animaciones se encuentran junto a los botones de generación. **EEVEE** es el modo rápido predeterminado: conserva 1920 × 1080 y las duraciones de la plantilla, con 32 muestras y sin trazado de rayos de EEVEE. **CYCLES** mantiene la opción de calidad anterior. La iluminación y los reflejos pueden variar entre motores; comprueba el resultado con Vista del programa.

Se preparan Campo, Coches y ambas victorias antes de empezar, pero solo se renderizan los vídeos que no coinciden con la biblioteca. **Cargar preparación** sigue permitiendo recuperar un `manifest.json` de una exportación anterior si coincide con los datos y contenidos actuales.

#### Biblioteca automática

Se guarda en **`%LOCALAPPDATA%/Piruleta Studio/Biblioteca`**, fuera de la carpeta de cada versión para conservarla entre actualizaciones. El panel muestra la ruta completa y permite abrirla.

- **logos/** y **calcomanias/** guardan copias al continuar con una serie válida. Se comparan mediante SHA-256: el mismo contenido se reutiliza aunque cambie el nombre o la carpeta. No se comparan solo los nombres ni se interpretan como iguales imágenes visualmente parecidas con archivos distintos.
- **catalogo.json** conserva los nombres originales de los archivos y su referencia interna. La configuración de la serie pasa a usar las copias guardadas y deja de depender de que los originales sigan en Descargas.
- **videos/** guarda los clips completos generados a partir de esta versión y sus comprobaciones de integridad. Un vídeo incompleto o dañado no se reutiliza.
- Los vídeos se distinguen por equipos, nombres, abreviaturas, coches, colores, contenido de logos/calcomanías, cabecera, motor y revisión de plantilla/modelos/trabajador. Cambiar solo BO o ronda no vuelve a renderizar las animaciones.
- Si cambia un equipo, se generan su victoria y el prepartido; se reutiliza la victoria del otro. Si intercambias los equipos entre series, pueden reutilizarse ambas victorias. El prepartido depende del orden de los dos equipos.
- EEVEE y Cycles tienen vídeos independientes. No se utiliza un render de un motor como sustituto automático del otro.
- Si los cuatro clips coinciden, se habilita el inicio sin necesitar ejecutar Blender. Si pulsas Preparar vídeos igualmente, se copian los clips recuperados a una nueva carpeta de salida junto a su manifest, sin render.

Las preparaciones de versiones anteriores siguen cargándose manualmente con **Cargar preparación**; no se buscan ni se atribuyen automáticamente a EEVEE. Los vídeos propios se siguen seleccionando desde su apartado independiente.

Para usar vídeos propios, selecciona **Campo**, **Coches**, **Victoria equipo A** y **Victoria equipo B** y pulsa **Usar estos vídeos**. Se admiten **MP4 con vídeo H.264**, se comprueba que tengan metadatos de vídeo y una duración válida y se respeta esa duración en el flujo. Comprueba la reproducción desde **Vista del programa** antes de emitir. No se ejecuta Blender para importar vídeos. Los archivos deben seguir disponibles en sus rutas.

Puedes mostrar prepartido o cualquiera de las victorias manualmente y cortar la animación desde esta categoría. Los vídeos de victoria A/B corresponden a los equipos de los datos iniciales, aunque después intercambies sus lados en Marcador.

### Estadísticas

Este apartado solo controla su aparición; no hay editor de jugadores ni de valores estadísticos.

- La aparición automática está activada por defecto y dura **10 segundos** después de cada partido.
- En el partido que decide la serie, se reproduce primero la victoria completa y después las estadísticas.
- **Mostrar hasta que las quite** permite mantenerlas sin límite; **Mostrar con temporizador** respeta la duración elegida y **Ocultar estadísticas** las retira al instante.
- Puedes añadir 10 segundos, pausar/reanudar el temporizador o desactivar la aparición automática. Ocultar estadísticas no corta una victoria que todavía se está reproduciendo.

### Emisión y OBS

Permite volver al partido, mostrar el cierre, cortar/alargar/pausar la escena actual y utilizar el control opcional de escenas de OBS por WebSocket. La URL única permanece visible en la parte superior de todas las categorías.

**Guardar datos / Cargar datos**, en el formulario inicial, conserva los equipos y las rutas de Blender y salida; los perfiles de diseño del marcador se guardan desde Marcador. No se guardan contraseñas ni se continúa automáticamente una emisión interrumpida.

## Rocket League y OBS

Cierra las apps independientes Overlay y Estadísticas mientras utilizas Studio. Studio utiliza una sola conexión TCP a `127.0.0.1:49123` y reconecta automáticamente. Si ya tenías activada Stats API no necesitas modificarla. Para una instalación nueva, consulta [Stats API oficial](https://www.rocketleague.com/developer/stats-api?lang=en); la configuración usada por las apps de origen es:

```ini
[TAGame.MatchStatsExporter_TA]
PacketSendRate=10
Port=49123
WebPort=49124
```

Haz una copia del INI antes de editarlo con el juego cerrado. Requiere modo espectador para los datos de turbo. El reloj no avanza por su cuenta si se pierden datos.

El programa local normalmente se sirve en `http://127.0.0.1:18767/program`. Si el puerto está ocupado se elige uno libre; usa la dirección indicada por la app. También hay rutas `/overlay` y `/postmatch` para comprobación. No configures varias fuentes Programa diferentes: la fuente compartida conserva la precarga de las victorias.

Si utilizas el control opcional por WebSocket y se pierde la conexión, la app lo indica y reintenta conectar. Recupera la escena actual al reconectar. La fuente por URL sigue funcionando independientemente de esa conexión. Si OBS estaba cerrado durante una victoria de dos segundos, puedes repetirla desde el panel. Las peticiones opcionales siguen el [protocolo oficial obs-websocket 5](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md).

## Desarrollo y validación

```powershell
python -B -m unittest discover -s tests -v
```

Las 41 pruebas verifican el ciclo de serie, estadísticas y su visibilidad, temporizadores, controles del marcador, importación MP4, biblioteca de recursos por contenido, supervivencia de las copias al borrar los originales, reutilización total y parcial de vídeos, recuperación automática al configurar la misma serie, separación de motores, invalidación por cambios de plantilla y regeneración de clips dañados, además de conexión TCP/HTTP/WebSocket simulada. Las pruebas no sustituyen una emisión con Rocket League y OBS reales.

`vendor/` contiene una copia local del código y los recursos de IntroRocketLeague, OverlayRocketLeague y PostMatchRocketLeague. Studio reutiliza el receptor TCP y la representación de datos de Estadísticas y los diseños HTML originales. El trabajador Blender se adapta para no renderizar dos veces el prepartido. Los modelos y sus atribuciones se conservan en [CREDITOS](vendor/animations/CREDITOS.txt); se incluyen las licencias de los recursos de las apps de origen.

`data/` contiene renders y registros locales y no se incluye en Git. El código no modifica los repositorios de origen. No incluye instalador; la distribución es portable. Para compilar, instala PyInstaller en tu entorno de desarrollo y ejecuta `./build.ps1 -Python RUTA_A_PYTHON`. La versión portable conserva sus datos junto al ejecutable. El lanzador registra errores de inicio en `inicio.log`.

La prueba opcional `python -B tests/smoke_blender.py` comprueba con Blender real la carga de coches y plantilla y exporta dos fotogramas de prepartido y ambas victorias con EEVEE a 1080p, más imágenes de comprobación a 960 × 540. `--cycles` permite comprobar Cycles con vídeos de baja resolución. Estas secuencias breves se guardan en data/smoke_EEVEE o data/smoke_CYCLES y no son preparaciones para emitir ni se incorporan a la biblioteca de producción.

`python -B tests/smoke_library.py` comprueba el flujo completo con Blender real: genera tres clips EEVEE de dos fotogramas a 1080p y repite la preparación verificando que no se ejecuta Blender de nuevo. Utiliza una biblioteca de prueba aislada dentro de data/smoke_library.

Cámaras actualizadas: prepartido de 13 segundos (plano abierto → coche A → giro rápido al coche B → centro → plano inicial); victoria de 4 segundos con giro lateral más amplio. Para ver el nuevo recorrido, genera de nuevo los vídeos. Los MP4 ya exportados conservan su animación. El identificador interno 02_VICTORIA_2s se mantiene por compatibilidad; su duración real es de 4 segundos.


## Versión 0.5

Las estadísticas automáticas esperan a `PodiumStart` y aparecen 3 segundos después, durante 10 segundos por defecto. La API oficial indica el inicio del podio, sin un evento específico que confirme cuándo termina la presentación del MVP. Si no llega el aviso del podio, se sigue viendo el juego y puedes mostrar las estadísticas desde el panel. En el último partido, el orden es podio/MVP → victoria → estadísticas: la victoria comienza 3 segundos después del aviso del podio y las estadísticas esperan al final de la animación. Los botones manuales permiten anticipar o cancelar la aparición.

La URL del programa aplica fundidos a negro de 800 ms al entrar y salir de estadísticas, prepartido y victorias (300 ms hasta negro, 200 ms manteniendo el negro y 300 ms para revelar la siguiente escena). Con la conexión opcional de OBS, las escenas comparten esa fuente y sus cambios son inmediatos para evitar aplicar otra transición encima.

En Marcador → Diseño puedes cambiar los colores de ambos equipos, del fondo y del texto. Las estadísticas usan la paleta actual del marcador, incluso para resultados ya guardados. Estos cambios no modifican los datos de serie ni invalidan los vídeos preparados: las animaciones conservan los colores elegidos en Datos de serie.

## Versión 0.6

El marcador aparece solo durante el juego, incluidas las pausas y repeticiones. Se oculta al finalizar el partido, durante el podio, las estadísticas y las cinemáticas. La URL independiente del marcador respeta también este estado; las vistas de ejemplo siguen disponibles.

Al terminar la última pantalla de estadísticas de la serie, el panel indica el final y vuelve a Datos de la serie con los equipos vacíos. El resultado final permanece en OBS mientras rellenas la siguiente serie. Las barras de victorias se alinean con los bordes de los logos; Elementos usa casillas con marca de verificación.

El prepartido sitúa los nombres blancos entre los logos y los coches, sin paneles de fondo. Debes preparar nuevos vídeos para ver la nueva composición (los anteriores siguen pudiendo cargarse manualmente). Las tomas de cámara y la duración se conservan.

El programa reproduce un fragmento de 8 segundos de arranque de motor al comenzar el vídeo de prepartido, a volumen moderado, y lo detiene si se cambia de escena. Funciona también con vídeos manuales: el sonido lo añade la fuente del programa, no está incrustado en el MP4. En OBS el audio sale por la fuente de navegador: comprueba que su canal no esté silenciado. Autor: Joseph Sardin / BigSoundBank, CC0. Procedencia y adaptación en `vendor/audio/CREDITOS.txt` y en `_internal/vendor/audio/CREDITOS.txt` de la versión portable.

## Versión 0.6.1

Las nuevas series usan marcador rounded, tipografía Verdana y marca del torneo oculta. Puedes volver a mostrarla en Marcador → Elementos. En Marcador → Textos, Logo del torneo permite elegir un PNG/JPG de hasta 4 MB o restablecer el logo de Piruleta. Se guarda al guardar el perfil del marcador; cargar perfiles existentes conserva sus ajustes explícitos.

La generación de Blender elimina los discos de fondo detrás de los escudos y conserva los logos. Prepara nuevos vídeos para aplicar este cambio; los vídeos ya renderizados no se modifican.

En la 0.6.1 el último partido automático sigue el orden podio/MVP → victoria → estadísticas. La victoria espera al aviso PodiumStart más 3 segundos, se reproduce completa y después aparecen las estadísticas. Si las estadísticas están desactivadas se mantiene el MVP y la victoria, y después termina la serie. Los botones manuales siguen permitiendo adelantar las escenas.

La ventana y el ejecutable usan el icono de la piruleta del logo; el icono multirresolución está en `vendor/branding/piruleta.ico`.

## Estadísticas actualizadas

Se integran los cambios de PostMatchRocketLeague: la última fila muestra TURBO USADO, una estimación acumulada por jugador (100 equivale a un depósito). Solo cuenta las bajadas observadas al usar turbo; las recogidas entre muestras pueden ocultar parte del consumo. Descarta comparaciones durante repeticiones, pausas, demoliciones y cambios de ronda. Si faltan datos se muestra un guion; conectarse a mitad de partido solo permite medir lo observado desde entonces.

Studio conserva el total del partido finalizado mientras se muestran las escenas y lo reinicia para el siguiente partido. Mantiene sus colores en directo, perfiles, logo del torneo y orden MVP → victoria → estadísticas. No es necesario regenerar los vídeos de Blender.

## Versión 0.7 · integración de las tres apps

Preparar vídeos produce cuatro clips: Campo (15 s, 1080p60), Coches (13 s) y una victoria por equipo (4 s). Campo utiliza el mismo exportador rápido de la app de animaciones: composición directa y H.264, sin Blender. En Blender y animaciones puedes elegir Champions Field, Mannfield o Estadio DFH. Coches utiliza la nueva arena envolvente, ruedas Dieci, faros y escudos iluminados. La biblioteca conserva cada clip completo y reutiliza coincidencias. Cambiar solo EEVEE/Cycles reutiliza Campo, cuyo motor siempre es rápido.

Al pulsar Iniciar serie aparece la elección Campo/Coches. Ambas aperturas pasan al juego y conservan el resto del flujo. Campo también tiene archivo manual y botón de emisión manual. Las preparaciones antiguas de tres vídeos siguen siendo válidas para Coches; Campo se habilita cuando añades su cuarto vídeo. El motor de arranque suena solo en Coches.

Estadísticas muestra solo duración predeterminada, mostrar hasta ocultar, ocultar y selección ordenada de entre 1 y 6 métricas básicas. Incluye puntos, goles, asistencias, tiros, salvadas, toques de balón, contactos entre coches, demoliciones y turbo usado. Menos de seis filas se centran y usan las nuevas barras. No se añaden los controles de periodo, agregación ni las estadísticas avanzadas de la app individual. Se mantienen el color del marcador y el orden MVP → victoria → estadísticas del último partido.

Marcador incorpora fondos de turbo y estadísticas independientes para cada equipo y el cambio de fondo degradado/plano. Conserva los checks, las barras alineadas con los logos, el logo de torneo configurable y los perfiles anteriores. Las repeticiones de goles siguen visibles; los archivos de repetición y las partidas públicas identificadas se ocultan.

Para ejecutar el código fuente con Campo rápido instala las dependencias de `requirements.txt`; el ejecutable portable ya las incluye. Las apps individuales no se modifican. Genera nuevos vídeos para usar la arena nueva y Campo.
