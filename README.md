# Buscador Histórico de EANs (`ean_history_search.py`)

## Descripción General

Este script permite buscar información histórica y actual sobre códigos EAN (European Article Number) a través de múltiples fuentes públicas en internet. Utiliza técnicas de web scraping, análisis de contenido y consultas a APIs abiertas para obtener datos relevantes sobre productos identificados por su EAN, incluyendo si han sido descatalogados, versiones anteriores, fechas de lanzamiento, y más.

El objetivo principal es facilitar la investigación de la historia de productos a partir de su código EAN, útil para áreas como investigación de mercados, análisis de portafolio, seguimiento de productos discontinuados, y control de inventarios históricos.

---

## Características Principales

- **Búsqueda Multi-fuente:**
  - Google Search (scraping de resultados y análisis de páginas encontradas)
  - Wayback Machine (snapshots históricos de páginas)
  - Amazon (búsqueda básica de productos)
  - OpenFoodFacts (API pública de productos alimenticios)
- **Paralelización:** Utiliza `ThreadPoolExecutor` para acelerar la búsqueda y el análisis de múltiples fuentes y términos en paralelo.
- **Rotación de User-Agent y Proxy:** Para evitar bloqueos y mejorar la robustez del scraping.
- **Validación de EAN:** Soporta EAN-8, EAN-13 (con verificación de dígito de control) y EAN-14.
- **Análisis de Contenido:**
  - Extrae contexto relevante alrededor del EAN en las páginas encontradas.
  - Detecta si la información es histórica, actual o indeterminada mediante patrones de texto.
  - Extrae posibles nombres de producto, fechas y fragmentos relevantes.
- **Exportación a CSV:** Permite guardar los hallazgos en un archivo CSV estructurado.
- **Logging detallado:** Muestra estadísticas, hallazgos y posibles errores en consola y/o archivo.
- **Configuración flexible:** Permite ajustar número de resultados, idioma, proxies, nivel de logging y archivo de log.

---

## ¿Cómo Funciona?

1. **Inicialización:**
   - Se recibe el EAN y parámetros opcionales desde la línea de comandos.
   - Se valida el EAN y se preparan los términos de búsqueda.
2. **Búsqueda en Fuentes Externas:**
   - Se consulta OpenFoodFacts, Wayback Machine y Amazon en paralelo.
3. **Búsqueda en Google:**
   - Se generan múltiples términos de búsqueda relacionados con el EAN.
   - Se realiza scraping de los resultados de Google para cada término.
   - Se extraen URLs relevantes y se analiza el contenido de cada una.
4. **Análisis de Contenido:**
   - Se buscan menciones del EAN y se extrae contexto.
   - Se aplican patrones para identificar nombre de producto, fechas y si la información es histórica o actual.
5. **Presentación y Exportación:**
   - Se agrupan y muestran los hallazgos por tipo (Histórico, Actual, Indeterminado, OpenFoodFacts, Wayback, Amazon).
   - Se pueden exportar los resultados a un archivo CSV.

---

## Ejemplo de Uso

```bash
python ean_history_search.py 1234567890123 --max-results 10 --lang es --log-level INFO
```

Parámetros principales:
- `ean` (obligatorio): Código EAN a buscar (8, 13 o 14 dígitos)
- `--max-results`: Número máximo de resultados por término de búsqueda (default: 10)
- `--lang`: Idioma de búsqueda (default: es)
- `--proxy`: Proxy HTTP/S a usar (puede usarse varias veces)
- `--log-level`: Nivel de logging (DEBUG, INFO, WARNING, ERROR)
- `--log-file`: Archivo para guardar logs

---

## Estructura del Script

- **Clase `EANHistoryFinder`:**
  - Métodos para búsqueda, análisis, extracción de contenido y exportación.
  - Manejo de sesión HTTP, rotación de User-Agent y proxies.
- **Funciones auxiliares:**
  - `parse_arguments()`: Parseo de argumentos de línea de comandos.
  - `setup_logging()`: Configuración de logging.
  - `main()`: Orquestador principal.

---

## Alcances y Limitaciones

### Alcances
- Permite identificar si un producto EAN está descatalogado, es histórico o sigue vigente.
- Extrae contexto textual relevante de páginas públicas.
- Puede ser extendido fácilmente para nuevas fuentes o patrones de análisis.

### Limitaciones
- El scraping de Google y Amazon puede estar sujeto a bloqueos o cambios en el HTML.
- No accede a bases de datos privadas ni fuentes de pago.
- La precisión depende de la información pública disponible y de los patrones de texto definidos.
- El análisis de contexto es heurístico y puede requerir ajustes para casos específicos.

---

## Requisitos

- Python 3.7+
- Paquetes:
  - `requests`
  - `beautifulsoup4`
  - `python-dotenv`
  - `tenacity` (opcional, para reintentos avanzados)

Instalación de dependencias:
```bash
pip install requests beautifulsoup4 python-dotenv tenacity
```

---

## Ideas para Mejoras Futuras

- Añadir más fuentes especializadas (bases de datos de productos, sitios de subastas, etc.)
- Mejorar el análisis de contexto con NLP (procesamiento de lenguaje natural)
- Implementar una interfaz gráfica o API web
- Soporte para otros tipos de códigos (UPC, ISBN, etc.)
- Mejorar la detección de duplicados y la agrupación de hallazgos
- Añadir tests automáticos y validaciones más robustas

---

## Autoría y Licencia

Desarrollado por Gilberto Nava Marcos.

Este script es de uso libre para fines educativos y de investigación. Se recomienda respetar los términos de uso de las páginas web consultadas y no realizar scraping masivo.

