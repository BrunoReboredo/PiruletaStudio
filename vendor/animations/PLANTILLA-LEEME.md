# Usar la plantilla

Archivo principal: **RLCS_Studio.blend**. Contiene las escenas **01_PREPARTIDO_13s** y **02_VICTORIA_2s** en un solo archivo. La demo de Portal Draco contra Goat está separada en **demos/Demo_PD_GOAT.blend**.

## Personalizar

- Nombres: busca objetos que empiecen por **NOMBRE |**, selecciónalos y pulsa Tab para editar el texto.
- Abreviaturas: objetos **ABREVIATURA | A** y **ABREVIATURA | B**.
- Colores: materiales **TEAM_A | Color editable** y **TEAM_B | Color editable**.
- Skins: selecciona la carrocería, abre Shading y, en los materiales EQUIPO_A/EQUIPO_B, abre tu imagen en el nodo **SKIN | Editable**. Conserva el mapa UV y las conexiones: A utiliza una skin de Octane y B una de Fennec.
- Escudos: abre tu PNG con transparencia en el material del objeto **ESCUDO | A** o **ESCUDO | B**. Activa el objeto en visor y render. Oculta el texto de abreviatura si se superpone. El escudo de victoria está preparado en el centro del panel y comparte el material de B.

## Elegir ganador

Por defecto aparece B. Para A: oculta la colección **GANADOR B | Fennec** y activa **GANADOR A | Octane (oculto)** en visor y render. Cambia los textos **NOMBRE | Ganador** y **NOMBRE | Placa ganador**. Asigna TEAM_A al panel, la banda del título y el aro de victoria, y el material del escudo A al objeto ESCUDO del ganador. Son cambios manuales; los nombres no se sincronizan automáticamente entre objetos.

## Guardar y renderizar

Antes de compartir el archivo, usa **Archivo → Datos externos → Empaquetar recursos** y guarda. Guarda una copia para cada enfrentamiento para conservar la plantilla vacía.

Teclado numérico 0: cámara. Espacio: reproducir. F12: render. Resolución 1920 × 1080; porcentaje 50 para previsualización y 100 para salida final.

La guía también está incluida como texto dentro del .blend. Los scripts de construcción y personalización conservados en el repositorio sobrescriben los archivos generados; no los ejecutes para cambiar un nombre o una skin.

Cámaras: prepartido de 13 segundos con acercamiento a ambos coches, giro rápido y regreso al plano inicial; victoria de 4 segundos con barrido lateral más amplio. Regenera los vídeos para aplicar el cambio. El nombre interno 02_VICTORIA_2s se conserva por compatibilidad; dura 4 segundos.

