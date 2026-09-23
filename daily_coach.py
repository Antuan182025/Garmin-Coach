#!/usr/bin/env python3
"""
Coach diario de Garmin - version gratuita
-----------------------------------------
Gemini (free tier) + FitMCP (remoto) + Telegram.
Pensado para ejecutarse desde GitHub Actions, sin infraestructura propia.

Local:  pip install google-genai mcp requests
        python daily_coach.py --dry-run
"""

import os
import sys
import asyncio
import datetime as dt

import requests
from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.sse import sse_client        # FitMCP usa transporte SSE

# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------

MODEL = "gemini-3-flash"          # free tier: 1.500 peticiones/dia

# El enlace privado de FitMCP (https://fitmcp.tech/sse/XXXXXXXX) YA lleva la
# credencial dentro de la propia URL: no hace falta token aparte.
FITMCP_URL = os.environ["FITMCP_URL"]

SYSTEM_PROMPT = """Eres el entrenador personal y analista de datos de Antonio.
Cada manana analizas sus metricas de Garmin y le escribes un mensaje breve,
directo y accionable, en espanol.

PERFIL
- Corredor de fondo, 4-5 sesiones por semana.
- Objetivo: media maraton en 1h30 (ritmo ~4:30/km). Ritmo maraton objetivo ~4:45/km.
- Umbral de lactato: 177 ppm.
- Trabajo de oficina, horario estandar, base en Madrid.

REGLAS
- Usa SIEMPRE las herramientas de FitMCP para obtener los datos. Nunca inventes cifras.
- Si una herramienta falla o no devuelve dato, escribe "sin dato" y no estimes.
- Compara cada metrica con la media de los ultimos 7 dias, no solo el valor de ayer.
- Prioriza: recuperacion (HRV, sueno, FC reposo, Body Battery) > carga > sesion del dia.
- Si hay senales de fatiga (HRV bajo, FC reposo elevada, sueno <6h, carga aguda
  disparada), dilo sin rodeos y recomienda bajar intensidad.
- Maximo 250 palabras. Texto plano para Telegram, sin tablas ni markdown.
- Termina SIEMPRE con "Sesion recomendada hoy:" y una propuesta concreta:
  tipo de sesion, duracion y ritmo o zona objetivo.
"""

PROMPT = """Dame el informe de hoy. Consulta:
1. Sueno de anoche: duracion, fases y puntuacion.
2. HRV, frecuencia cardiaca en reposo y Body Battery de esta manana.
3. Actividades de ayer: distancia, ritmo, FC media, zonas y training effect.
4. Carga de entrenamiento aguda frente a cronica de los ultimos 7 dias.
5. Nivel de estres y pasos de ayer."""


# ---------------------------------------------------------------------------
# LOGICA
# ---------------------------------------------------------------------------

async def generar_informe() -> str:
    cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    async with sse_client(FITMCP_URL, timeout=60) as (read, write):
        async with ClientSession(read, write) as sesion:
            await sesion.initialize()

            # El SDK de Gemini acepta la sesion MCP como herramienta y gestiona
            # automaticamente las llamadas a las tools de FitMCP.
            respuesta = await cliente.aio.models.generate_content(
                model=MODEL,
                contents=PROMPT,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[sesion],
                    temperature=0.4,
                ),
            )
            return (respuesta.text or "").strip() or "Sin resultado del modelo."


def enviar_telegram(texto: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": texto,
            "disable_web_page_preview": True,
        },
        timeout=30,
    ).raise_for_status()


def main() -> None:
    hoy = dt.date.today().isoformat()
    try:
        informe = asyncio.run(generar_informe())
    except Exception as e:
        informe = (
            f"[ERROR {hoy}] No se pudo generar el informe de Garmin.\n"
            f"{type(e).__name__}: {e}"
        )

    print(informe)          # queda en el log de GitHub Actions

    if "--dry-run" in sys.argv:
        return

    try:
        enviar_telegram(informe)
    except Exception as e:
        print(f"Fallo al enviar por Telegram: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
