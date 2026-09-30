---
tags: [backend, pdf, debug, parser]
---

# PDF Parser — extracción y revisión

`pdf_parser.py` lee estadísticas de ventas e informes de situación. La detección de farmacia, tipo de documento y laboratorio conserva su comportamiento anterior.

## Límites de cada producto

`_layout` identifica las columnas en la cabecera de **cada página** y usa los rectángulos de las celdas cuando existen. Si no reconoce la tabla, aplica una lectura aproximada con el aviso `columnas_no_reconocidas`; esos datos no se consideran verificados.

`_product_blocks` delimita los productos mediante códigos y bandas de fondo. Sin bandas, usa la separación entre líneas y las filas de año. Si no puede decidir un límite con claridad, marca `limites_fila_inciertos`. Cada fragmento pertenece a un bloque: no se concatenan líneas mediante búsquedas hacia el producto anterior o siguiente.

`_description` recoge todas las líneas dentro de la celda de descripción. Los encabezados y los pies quedan fuera del cuerpo de la tabla. No se eliminan tamaños, colores, números de tono ni otras partes legítimas del nombre.

## Cifras desconocidas y validación

- `_integer` conserva signos negativos y cantidades grandes; un campo ilegible se devuelve como `None`, nunca como cero.
- Se conserva el total impreso y se compara exactamente con la suma de los doce meses. Una diferencia produce `total_discrepancia`.
- Stock, mínimo, meses o totales ausentes quedan señalados con `campo_ausente`.
- Los códigos repetidos conservan sus procedencias y generan un aviso.
- Los datos numéricos o límites dudosos impiden calcular pedidos automáticos. La interfaz y los PDF muestran «Revisar» para cantidades desconocidas.
- Un PDF de ventas sin productos legibles detiene la comparativa con un error que identifica la farmacia.

## Descripciones y procedencia

`compare_products` consulta las descripciones de ventas y situación de ambas farmacias. Prioriza candidatos con límites fiables y nombres válidos; una cadena más larga no gana por su longitud. Las diferencias entre fuentes se muestran para revisión.

Cada resultado conserva `sources`, `description_candidates` y `description_source`, con archivo, página, coordenadas, farmacia y tipo de informe. El panel del producto permite abrir la página original. Los nombres de archivo corresponden a los documentos subidos, no a archivos temporales internos.

Las descripciones se imprimen completas con altura de fila adaptable en los PDF de comparativa, plantilla y pedido.

## Lectura visual alternativa

Si hay una clave Anthropic configurada, `_apply_vision_fallback` envía recortes de las filas dudosas a la lectura visual, con un máximo de ocho filas por documento. Solo acepta el mismo código y una estructura válida; los meses deben tener doce valores y cuadrar con el total impreso. No sobrescribe cifras ya verificadas para reparar únicamente un nombre.

Los errores del servicio o renderizador y las respuestas rechazadas quedan como avisos. Un nombre ausente en el propio original, como `8` o `07/2026`, no se completa por imaginación. Las filas que no se resuelven mantienen su estado de revisión.

Este mecanismo no garantiza todos los formatos posibles. Un documento nuevo con cabeceras, códigos o estructura desconocidos requiere revisión y un ejemplo visual antes de ampliar el lector. Los PDF completamente escaneados sin texto todavía necesitan una extracción visual completa aparte.

## Pruebas

Desde la raíz del proyecto, usando el Python del entorno instalado:

```bash
bin/python -B -m pytest -q -p no:cacheprovider
```

Las pruebas sintéticas cubren descripciones de varias líneas, códigos al principio o al final del bloque, páginas sin bandas, columnas desplazadas, negativos, cifras grandes, totales discrepantes, campos desconocidos, procedencia y respuestas visuales inválidas. El flujo de cuatro documentos comprueba subida, comparación, resultados y descarga sin contraseña.

Los originales privados de Interapothek no están en el repositorio. Para habilitar las regresiones verificadas visualmente:

```bash
PHARMACY_PDF_FIXTURE_DIR=/ruta/a/los/cuatro/originales bin/python -B -m pytest -q -p no:cacheprovider
```

Se han comprobado, entre otros, agua de 5000 ml, algodón de 50 g, cepillo coral, lipgloss Nº3, devoluciones negativas y stock negativo. Las ventas coinciden con los totales originales: Zarzuelo 539/1034 y Barris 700/1863 para 2026/2025.
