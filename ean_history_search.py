# Buscador Histórico de EANs (Versión o3 mini)

# Este script busca información histórica sobre números EAN específicos utilizando
# búsquedas directas en Google y análisis de contenido con BeautifulSoup.

# Uso:
#     python ean_history_search_v4.py <número_ean>

import os
import sys
import json
import time
import argparse
import re
import csv
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import random
from functools import wraps

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
except ImportError:
    retry = None  # fallback si tenacity no está instalado

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import concurrent.futures
import logging

# Cargar variables de entorno desde archivo .env
load_dotenv()

# Configuración de User-Agent para solicitudes HTTP
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Lista de User-Agents para rotación
USER_AGENTS = [
    USER_AGENT,
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def retry_on_exception(max_attempts=3):
    """Decorador simple de reintentos con backoff exponencial."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = 1
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
                    delay *= 2
        return wrapper
    return decorator

# Configuración de búsqueda
MAX_RESULTS = 10
SEARCH_TIMEOUT = 30  # segundos

# Configuración de logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class EANHistoryFinder:
    """Clase principal para buscar información histórica de EANs."""
    
    def __init__(self, ean: str, proxies: Optional[List[str]] = None, max_results: int = MAX_RESULTS, lang: str = "es"):
        """
        Inicializa el buscador con un número EAN específico.
        
        Args:
            ean (str): El número EAN a buscar.
        """
        self.ean = ean
        self.results = []
        self.max_results = max_results
        self.lang = lang
        self.proxies = proxies or []
        self.proxy_index = 0
        # Ampliar términos de búsqueda para mejorar resultados
        self.search_terms = [
            f"{ean}",  # Búsqueda directa del EAN
            f"{ean} producto",
            f"{ean} código de barras",
            f"{ean} barcode",  # Término en inglés
            f"{ean} upc",  # Término alternativo
            f"{ean} histórico",
            f"{ean} descatalogado",
            f"{ean} versión anterior",
            f"código de barras {ean}",  # Variación en el orden
            f"barcode {ean}",  # Variación en inglés
            f"EAN {ean}"  # Especificar que es un EAN
        ]
        # Añadir objeto Session para mayor eficiencia y robustez
        self.session = requests.Session()
        self.rotate_user_agent()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
            "Referer": "https://www.google.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })
    
    def rotate_user_agent(self):
        ua = get_random_user_agent()
        self.session.headers.update({"User-Agent": ua})

    def get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.proxy_index % len(self.proxies)]
        self.proxy_index += 1
        return {"http": proxy, "https": proxy}

    # Decorador de reintentos (usa tenacity si está disponible)
    def retryable(self, func):
        if retry:
            return retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type((requests.RequestException,))
            )(func)
        else:
            return retry_on_exception(3)(func)

    def _request_with_retry(self, url, **kwargs):
        # Rotar User-Agent y proxy en cada intento
        self.rotate_user_agent()
        proxy = self.get_next_proxy()
        if proxy:
            kwargs["proxies"] = proxy
        return self.session.get(url, timeout=SEARCH_TIMEOUT, **kwargs)
    
    def validate_ean(self) -> bool:
        """
        Valida si el EAN proporcionado es válido.
        
        Returns:
            bool: True si el EAN es válido, False en caso contrario.
        """
        # Verificar que el EAN contenga solo dígitos
        if not self.ean.isdigit():
            return False
        
        # Verificar longitud (EAN-8, EAN-13, EAN-14 son los formatos más comunes)
        valid_lengths = [8, 13, 14]
        if len(self.ean) not in valid_lengths:
            return False
        
        # Para EAN-13, podemos verificar el dígito de control
        if len(self.ean) == 13:
            # Algoritmo para verificar el dígito de control de EAN-13
            total = 0
            for i in range(12):
                digit = int(self.ean[i])
                total += digit if i % 2 == 0 else digit * 3
            
            check_digit = (10 - (total % 10)) % 10
            return check_digit == int(self.ean[12])
        
        # Para otros formatos, simplemente aceptamos si tienen la longitud correcta
        return True
    
    def search_with_requests(self, query: str) -> List[Dict]:
        """
        Busca en Google utilizando requests y BeautifulSoup, con reintentos y rotación de User-Agent/proxy.
        """
        @self.retryable
        def _search():
            encoded_query = requests.utils.quote(query)
            google_domains = [
                f"https://www.google.com/search?hl={self.lang}",
                f"https://www.google.es/search?hl={self.lang}",
                f"https://www.google.com.mx/search?hl={self.lang}"
            ]
            results = []
            for domain in google_domains:
                url = f"{domain}&q={encoded_query}&num={self.max_results}"
                try:
                    response = self._request_with_retry(url)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "html.parser")
                        selectors = ["div.g", "div.tF2Cxc", "div.yuRUbf", "div.rc"]
                        search_results = []
                        for selector in selectors:
                            search_results = soup.select(selector)
                            if search_results:
                                break
                        if not search_results:
                            search_results = soup.find_all("a", href=lambda href: href and href.startswith("http") and "google" not in href)
                        domain_results = []
                        if search_results:
                            for result in search_results:
                                try:
                                    if selector in selectors[:4]:
                                        title_element = result.select_one("h3")
                                        title = title_element.get_text() if title_element else "Sin título"
                                        link_element = result.select_one("a")
                                        link = link_element["href"] if link_element and "href" in link_element.attrs else ""
                                        snippet = ""
                                        snippet_selectors = ["div.VwiC3b", "div.IsZvec", "span.st", "div.s"]
                                        for s_selector in snippet_selectors:
                                            snippet_element = result.select_one(s_selector)
                                            if snippet_element:
                                                snippet = snippet_element.get_text()
                                                break
                                    else:
                                        title = result.get_text() or "Sin título"
                                        link = result["href"]
                                        snippet = ""
                                    if link and link.startswith("http") and "google" not in link:
                                        domain_results.append({
                                            "title": title,
                                            "link": link,
                                            "snippet": snippet
                                        })
                                except Exception as e:
                                    continue
                        if domain_results:
                            results.extend(domain_results)
                            break
                except Exception as e:
                    continue
            unique_results = []
            seen_urls = set()
            for result in results:
                if result["link"] not in seen_urls:
                    seen_urls.add(result["link"])
                    unique_results.append(result)
            return unique_results
        return _search()

    def search_wayback_machine(self) -> Optional[Dict]:
        """
        Busca snapshots históricos del producto en Wayback Machine.
        """
        url = f"https://archive.org/wayback/available?url=https://www.google.com/search?q={self.ean}"
        try:
            response = self._request_with_retry(url)
            if response.status_code == 200:
                data = response.json()
                snapshots = data.get("archived_snapshots", {})
                if "closest" in snapshots:
                    snap = snapshots["closest"]
                    return {
                        "url": snap.get("url"),
                        "findings": [{
                            "product_name": "Wayback Snapshot",
                            "date_clue": snap.get("timestamp", "No identificado"),
                            "assessment": "Wayback",
                            "snippet": f"Snapshot de Google para EAN {self.ean}",
                            "url": snap.get("url")
                        }]
                    }
        except Exception as e:
            logging.error(f"Error en búsqueda en Wayback Machine: {str(e)}")
        return None

    def search_amazon(self) -> Optional[Dict]:
        """
        Busca el EAN en Amazon (búsqueda básica, sin scraping profundo).
        """
        url = f"https://www.amazon.com/s?k={self.ean}"
        try:
            # Solo obtener la página de resultados, no scrapea productos individuales
            response = self._request_with_retry(url)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                title = soup.title.get_text() if soup.title else "Amazon Search"
                return {
                    "url": url,
                    "findings": [{
                        "product_name": title,
                        "date_clue": "No identificado",
                        "assessment": "Amazon",
                        "snippet": f"Resultados de búsqueda de Amazon para EAN {self.ean}",
                        "url": url
                    }]
                }
        except Exception as e:
            logging.error(f"Error en búsqueda en Amazon: {str(e)}")
        return None

    def search_openfoodfacts(self) -> Optional[Dict]:
        """
        Busca información del producto en OpenFoodFacts.
        
        Returns:
            Optional[Dict]: Hallazgo con información del producto o None si no se encuentra.
        """
        url = f"https://es.openfoodfacts.org/api/v0/product/{self.ean}.json"
        try:
            response = self._request_with_retry(url)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == 1:
                    product = data.get("product", {})
                    product_name = product.get("product_name", "No identificado")
                    snippet = product.get("generic_name", "")
                    date_clue = product.get("created_t", "No identificado")
                    if isinstance(date_clue, (int, float)):
                        date_clue = datetime.fromtimestamp(date_clue).strftime("%Y-%m-%d")
                    finding = {
                        "product_name": product_name,
                        "date_clue": date_clue,
                        "assessment": "OFProduct",
                        "snippet": snippet,
                        "url": f"https://es.openfoodfacts.org/product/{self.ean}"
                    }
                    return {"url": f"https://es.openfoodfacts.org/product/{self.ean}", "findings": [finding]}
                else:
                    logging.info("Producto no encontrado en OpenFoodFacts")
            else:
                logging.error(f"Error en OpenFoodFacts: Código de estado {response.status_code}")
        except Exception as e:
            logging.error(f"Error en búsqueda en OpenFoodFacts: {str(e)}")
        return None

    def search(self) -> List[Dict]:
        """
        Realiza la búsqueda de información histórica del EAN, paralelizando la obtención de resultados de Google.
        """
        all_results = []
        all_futures = []
        if not self.validate_ean():
            logging.error(f"Error: '{self.ean}' no es un número EAN válido.")
            return []
        logging.info("\n" + "=" * 50)
        logging.info(f"BUSCADOR HISTÓRICO DE EANs (V2)")
        logging.info("=" * 50)
        logging.info(f"Buscando información histórica para el EAN: {self.ean}")
        logging.info(f"Formato: {'EAN-8' if len(self.ean) == 8 else 'EAN-13' if len(self.ean) == 13 else 'EAN-14' if len(self.ean) == 14 else 'Desconocido'}")
        logging.info("=" * 50)
        start_time = time.time()
        # Paralelizar la obtención de resultados de Google
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            # Búsqueda en fuentes externas
            all_futures.append(executor.submit(self.search_openfoodfacts))
            all_futures.append(executor.submit(self.search_wayback_machine))
            all_futures.append(executor.submit(self.search_amazon))
            # Paralelizar búsquedas de términos en Google
            google_futures = {executor.submit(self.search_with_requests, term): term for term in self.search_terms}
            url_analysis_futures = []
            for future in concurrent.futures.as_completed(list(google_futures.keys())):
                term = google_futures[future]
                try:
                    results = future.result()
                    logging.info(f"Buscando: {term}... OK ({len(results)} resultados)")
                    for result in results[:3]:
                        url = result.get("link")
                        if not url:
                            continue
                        url_analysis_futures.append(executor.submit(self._process_url, url))
                except Exception as e:
                    logging.error(f"Error en búsqueda de '{term}': {str(e)}")
            # Analizar URLs encontradas
            all_futures.extend(url_analysis_futures)
            for future in concurrent.futures.as_completed(all_futures):
                analysis = future.result()
                if analysis and analysis.get("findings"):
                    all_results.append(analysis)
        execution_time = time.time() - start_time
        logging.info("\n" + "=" * 50)
        logging.info("ESTADÍSTICAS DE BÚSQUEDA")
        logging.info("=" * 50)
        logging.info(f"Términos de búsqueda utilizados: {len(self.search_terms)}")
        total_findings = sum(len(result["findings"]) for result in all_results)
        logging.info(f"Total de hallazgos: {total_findings}")
        logging.info(f"URLs con información relevante: {len(all_results)}")
        logging.info(f"Tiempo de ejecución: {execution_time:.2f} segundos")
        return all_results

    def _process_url(self, url: str) -> Optional[Dict]:
        logging.info(f"Analizando: {url}...")
        content = self.extract_content_from_url(url)
        if content:
            analysis = self.analyze_content(content, url)
            if analysis:
                logging.info(f"OK ({len(analysis['findings'])} hallazgos)")
                return analysis
            else:
                logging.info("Sin hallazgos")
        else:
            logging.info("Error al extraer contenido")
        return None
    
    def extract_content_from_url(self, url: str) -> str:
        """
        Extrae el contenido de una URL.
        
        Args:
            url (str): La URL a escanear.
            
        Returns:
            str: El contenido extraído de la página o cadena vacía si hay un error.
        """
        try:
            # Realizar la solicitud usando self.session
            response = self._request_with_retry(url)
            
            # Verificar si la solicitud fue exitosa
            if response.status_code == 200:
                # Parsear el HTML
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Eliminar scripts y estilos
                for script in soup(["script", "style"]):
                    script.extract()
                
                # Obtener texto
                text = soup.get_text()
                
                # Limpiar espacios en blanco
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\n'.join(chunk for chunk in chunks if chunk)
                
                return text
            else:
                logging.error(f"Error al extraer contenido de {url}: Código de estado {response.status_code}")
                return ""
                
        except Exception as e:
            logging.error(f"Error al extraer contenido de {url}: {str(e)}")
            return ""
    
    def analyze_content(self, content: str, url: str) -> Optional[Dict]:
        """
        Analiza el contenido extraído para buscar información histórica.
        
        Args:
            content (str): El contenido extraído de la página web.
            url (str): La URL de origen del contenido.
            
        Returns:
            Optional[Dict]: Resultados del análisis o None si no se encuentra información relevante.
        """
        if not content:
            return None
        
        # Buscar menciones del EAN (con variaciones para mayor flexibilidad)
        ean_patterns = [
            re.compile(r'\b' + re.escape(self.ean) + r'\b'),  # EAN exacto
            re.compile(r'EAN[\s:-]*' + re.escape(self.ean)),  # Con prefijo EAN
            re.compile(r'código[\s:-]*' + re.escape(self.ean)),  # Con prefijo código
            re.compile(r'barcode[\s:-]*' + re.escape(self.ean)),  # Con prefijo barcode
            re.compile(r'UPC[\s:-]*' + re.escape(self.ean))  # Con prefijo UPC
        ]
        
        findings = []
        
        # Buscar coincidencias con todos los patrones
        for pattern in ean_patterns:
            ean_matches = pattern.finditer(content)
            
            for match in ean_matches:
                # Extraer contexto alrededor de la mención del EAN (800 caracteres para más contexto)
                start = max(0, match.start() - 400)
                end = min(len(content), match.end() + 400)
                context = content[start:end]
                
                # Buscar nombre del producto con patrones ampliados
                product_name = "No identificado"
                product_patterns = [
                    r'(?:producto|artículo|item|product|item)[\s:]+([^\n\.]{5,50})',
                    r'(?:nombre|título|name|title)[\s:]+([^\n\.]{5,50})',
                    r'(?:modelo|referencia|model|reference)[\s:]+([^\n\.]{5,50})',
                    r'(?:descripción|description)[\s:]+([^\n\.]{5,50})',
                    r'(?:^|(?<=[\n\.]))([A-Z][^\n\.]{5,50})',  # Frases que comienzan con mayúscula
                    r'(?:^|(?<=[\n\.]))([^a-z\n\.]{5,50})'       # Texto en mayúsculas
                ]
                
                for pattern in product_patterns:
                    product_match = re.search(pattern, context, re.IGNORECASE)
                    if product_match:
                        product_name = product_match.group(1).strip()
                        break
                
                # Si no se encontró un nombre de producto, intentar extraerlo del título de la página
                if product_name == "No identificado" and "title" in content.lower():
                    title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
                    if title_match:
                        product_name = title_match.group(1).strip()
                
                # Buscar pistas temporales con patrones ampliados
                date_clue = "No identificado"
                date_patterns = [
                    r'(?:año|modelo|year|model)[\s:]+(\d{4})',
                    r'(?:versión|edición|version|edition)[\s:]+([^\n\.]{5,30})',
                    r'(?:descatalogado|discontinuado|obsoleto|discontinued|obsolete)',
                    r'(?:anterior|previo|antiguo|previous|old|former)',
                    r'(?:desde|hasta|entre|from|to|between)[\s:]+(\d{4})',
                    r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',  # Fechas en formato DD/MM/YYYY o similar
                    r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',  # Fechas en formato YYYY/MM/DD o similar
                    r'(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)[\s,]+(\d{4})',  # Meses en español + año
                    r'(?:january|february|march|april|may|june|july|august|september|october|november|december)[\s,]+(\d{4})'  # Meses en inglés + año
                ]
                
                for pattern in date_patterns:
                    date_match = re.search(pattern, context, re.IGNORECASE)
                    if date_match:
                        if date_match.groups():
                            date_clue = date_match.group(1).strip()
                        else:
                            date_clue = date_match.group(0).strip()
                        break
                
                # Evaluar si es histórico con indicadores ampliados
                assessment = "Indeterminado"
                historical_indicators = [
                    r'(?:descatalogado|discontinuado|obsoleto|discontinued|obsolete)',
                    r'(?:ya no|no disponible|not available|no longer)',
                    r'(?:versión anterior|modelo antiguo|previous version|old model)',
                    r'(?:reemplazado por|sustituido por|replaced by|substituted by)',
                    r'(?:histórico|historia|pasado|historic|history|past)',
                    r'(?:fue|era|was|were)',
                    r'(?:antiguo|antigüedad|antique|vintage)',
                    r'(?:colección|collection) (?:pasada|anterior|old)'
                ]
                
                current_indicators = [
                    r'(?:nuevo|actual|vigente|new|current)',
                    r'(?:disponible|en stock|available|in stock)',
                    r'(?:versión actual|último modelo|current version|latest model)',
                    r'(?:reciente|recién|recent|recently)',
                    r'(?:comprar|compra ahora|buy|buy now)',
                    r'(?:añadir al carrito|add to cart)',
                    r'(?:precio actual|current price)',
                    r'(?:envío|shipping) (?:gratis|gratuito|free)'
                ]
                
                historical_score = 0
                current_score = 0
                
                for pattern in historical_indicators:
                    if re.search(pattern, context, re.IGNORECASE):
                        historical_score += 1
                
                for pattern in current_indicators:
                    if re.search(pattern, context, re.IGNORECASE):
                        current_score += 1
                
                if historical_score > current_score:
                    assessment = "Histórico"
                elif current_score > historical_score:
                    assessment = "Actual"
                
                # Limpiar y formatear el snippet
                snippet = re.sub(r'\s+', ' ', context).strip()
                
                # Verificar si este hallazgo es único (evitar duplicados)
                is_duplicate = False
                for existing in findings:
                    if existing["snippet"] == snippet:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    findings.append({
                        "product_name": product_name,
                        "date_clue": date_clue,
                        "assessment": assessment,
                        "snippet": snippet,
                        "url": url
                    })
        
        # Si no se encontraron menciones exactas del EAN, buscar información general de la página
        if not findings and self.ean in content:
            # Extraer un fragmento general donde aparece el EAN
            ean_pos = content.find(self.ean)
            start = max(0, ean_pos - 400)
            end = min(len(content), ean_pos + 400)
            context = content[start:end]
            
            # Intentar extraer información básica
            product_name = "No identificado"
            
            # Intentar extraer del título de la página
            title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
            if title_match:
                product_name = title_match.group(1).strip()
            
            findings.append({
                "product_name": product_name,
                "date_clue": "No identificado",
                "assessment": "Indeterminado",
                "snippet": re.sub(r'\s+', ' ', context).strip(),
                "url": url
            })
        
        if findings:
            return {
                "url": url,
                "findings": findings
            }
        else:
            return None
    
    def format_results(self, results: List[Dict]) -> None:
        """
        Formatea y muestra los resultados de la búsqueda.
        
        Args:
            results (List[Dict]): Lista de resultados encontrados.
        """
        if not results:
            logging.info("\n" + "=" * 50)
            logging.info("No se encontraron resultados para el EAN proporcionado.")
            logging.info("Posibles razones:")
            logging.info("- El EAN no existe o no es común en fuentes públicas.")
            logging.info("- No hay información histórica disponible en línea.")
            logging.info("- Las fuentes que contienen esta información no son accesibles mediante scraping.")
            logging.info("=" * 50)
            return
        
        # Agrupar hallazgos por tipo de evaluación
        findings_by_assessment = {"Histórico": [], "Actual": [], "Indeterminado": [], "OFProduct": [], "Wayback": [], "Amazon": []}
        
        for result in results:
            for finding in result["findings"]:
                assessment = finding["assessment"]
                findings_by_assessment[assessment].append(finding)
        
        # Mostrar resumen
        logging.info("\n" + "=" * 50)
        logging.info("RESUMEN DE RESULTADOS")
        logging.info("=" * 50)
        
        total_findings = sum(len(findings) for findings in findings_by_assessment.values())
        logging.info(f"Total de hallazgos: {total_findings}")
        
        for assessment, findings in findings_by_assessment.items():
            logging.info(f"- {assessment}: {len(findings)}")
        
        # Mostrar hallazgos detallados por tipo de evaluación
        logging.info("\n" + "=" * 50)
        logging.info("RESULTADOS DETALLADOS")
        logging.info("=" * 50)
        
        # Primero mostrar hallazgos históricos
        if findings_by_assessment["Histórico"]:
            logging.info("\nHALLAZGOS HISTÓRICOS:")
            logging.info("-" * 50)
            
            for i, finding in enumerate(findings_by_assessment["Histórico"], 1):
                logging.info(f"Hallazgo #{i}:")
                logging.info(f"  URL: {finding['url']}")
                logging.info(f"  Producto: {finding['product_name']}")
                logging.info(f"  Pista temporal: {finding['date_clue']}")
                logging.info(f"  Fragmento: \"{finding['snippet'][:200]}...\"")
                logging.info("-" * 50)
        
        # Luego mostrar hallazgos actuales
        if findings_by_assessment["Actual"]:
            logging.info("\nHALLAZGOS ACTUALES:")
            logging.info("-" * 50)
            
            for i, finding in enumerate(findings_by_assessment["Actual"], 1):
                logging.info(f"Hallazgo #{i}:")
                logging.info(f"  URL: {finding['url']}")
                logging.info(f"  Producto: {finding['product_name']}")
                logging.info(f"  Pista temporal: {finding['date_clue']}")
                logging.info(f"  Fragmento: \"{finding['snippet'][:200]}...\"")
                logging.info("-" * 50)
        
        # Finalmente mostrar hallazgos indeterminados
        if findings_by_assessment["Indeterminado"]:
            logging.info("\nHALLAZGOS INDETERMINADOS:")
            logging.info("-" * 50)
            
            for i, finding in enumerate(findings_by_assessment["Indeterminado"], 1):
                logging.info(f"Hallazgo #{i}:")
                logging.info(f"  URL: {finding['url']}")
                logging.info(f"  Producto: {finding['product_name']}")
                logging.info(f"  Pista temporal: {finding['date_clue']}")
                logging.info(f"  Fragmento: \"{finding['snippet'][:200]}...\"")
                logging.info("-" * 50)
        
        # Mostrar hallazgos de OpenFoodFacts
        if findings_by_assessment["OFProduct"]:
            logging.info("\nHALLAZGOS DE OPENFOODFACTS:")
            logging.info("-" * 50)
            
            for i, finding in enumerate(findings_by_assessment["OFProduct"], 1):
                logging.info(f"Hallazgo #{i}:")
                logging.info(f"  URL: {finding['url']}")
                logging.info(f"  Producto: {finding['product_name']}")
                logging.info(f"  Pista temporal: {finding['date_clue']}")
                logging.info(f"  Fragmento: \"{finding['snippet'][:200]}...\"")
                logging.info("-" * 50)
        
        # Mostrar hallazgos de Wayback Machine
        if findings_by_assessment["Wayback"]:
            logging.info("\nHALLAZGOS DE WAYBACK MACHINE:")
            logging.info("-" * 50)
            
            for i, finding in enumerate(findings_by_assessment["Wayback"], 1):
                logging.info(f"Hallazgo #{i}:")
                logging.info(f"  URL: {finding['url']}")
                logging.info(f"  Producto: {finding['product_name']}")
                logging.info(f"  Pista temporal: {finding['date_clue']}")
                logging.info(f"  Fragmento: \"{finding['snippet'][:200]}...\"")
                logging.info("-" * 50)
        
        # Mostrar hallazgos de Amazon
        if findings_by_assessment["Amazon"]:
            logging.info("\nHALLAZGOS DE AMAZON:")
            logging.info("-" * 50)
            
            for i, finding in enumerate(findings_by_assessment["Amazon"], 1):
                logging.info(f"Hallazgo #{i}:")
                logging.info(f"  URL: {finding['url']}")
                logging.info(f"  Producto: {finding['product_name']}")
                logging.info(f"  Pista temporal: {finding['date_clue']}")
                logging.info(f"  Fragmento: \"{finding['snippet'][:200]}...\"")
                logging.info("-" * 50)
    
    def save_results_to_csv(self, results: List[Dict], filename: str = None) -> str:
        """
        Guarda los resultados en un archivo CSV.
        
        Args:
            results (List[Dict]): Lista de resultados encontrados.
            filename (str, optional): Nombre del archivo CSV. Si es None, se genera automáticamente.
            
        Returns:
            str: Ruta del archivo CSV generado.
        """
        if not results:
            return ""
        
        # Generar nombre de archivo si no se proporciona
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ean_{self.ean}_results_{timestamp}.csv"
        
        # Asegurar que la ruta sea absoluta
        if not os.path.isabs(filename):
            filename = os.path.join(os.getcwd(), filename)
        
        # Preparar datos para CSV
        csv_data = []
        
        for result in results:
            for finding in result["findings"]:
                csv_data.append({
                    "EAN": self.ean,
                    "URL": finding["url"],
                    "Producto": finding["product_name"],
                    "Pista_Temporal": finding["date_clue"],
                    "Evaluacion": finding["assessment"],
                    "Fragmento": finding["snippet"]
                })
        
        # Escribir CSV
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ["EAN", "URL", "Producto", "Pista_Temporal", "Evaluacion", "Fragmento"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for row in csv_data:
                    writer.writerow(row)
            
            logging.info(f"\nResultados guardados en: {filename}")
            return filename
            
        except Exception as e:
            logging.error(f"Error al guardar resultados en CSV: {str(e)}")
            return ""

def parse_arguments() -> argparse.Namespace:
    """
    Analiza los argumentos de línea de comandos.
    Returns:
        argparse.Namespace: Argumentos parseados.
    """
    parser = argparse.ArgumentParser(description="Buscador Histórico de EANs (WebScraping)")
    parser.add_argument("ean", help="Número EAN a buscar (8, 13 o 14 dígitos)")
    parser.add_argument("--max-results", type=int, default=10, help="Número máximo de resultados por término")
    parser.add_argument("--lang", type=str, default="es", help="Idioma de búsqueda (por ejemplo, es, en, fr)")
    parser.add_argument("--proxy", action="append", help="Proxy HTTP/S a usar (puede usarse varias veces)")
    parser.add_argument("--log-level", type=str, default="INFO", help="Nivel de logging (DEBUG, INFO, WARNING, ERROR)")
    parser.add_argument("--log-file", type=str, default=None, help="Archivo para guardar logs")
    return parser.parse_args()

def setup_logging(level: str, log_file: Optional[str] = None):
    numeric_level = getattr(logging, level.upper(), None)
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers
    )

def main():
    """Función principal del script."""
    try:
        args = parse_arguments()
        setup_logging(args.log_level, args.log_file)
        finder = EANHistoryFinder(
            args.ean,
            proxies=args.proxy,
            max_results=args.max_results,
            lang=args.lang
        )
        results = finder.search()
        finder.format_results(results)
        if results:
            finder.save_results_to_csv(results)
    except KeyboardInterrupt:
        logging.error("\n\nOperación cancelada por el usuario.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"\n\nError inesperado: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
