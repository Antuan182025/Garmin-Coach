#!/usr/bin/env python3
"""
Coach diario de Garmin - version gratuita
Gemini (free tier) + FitMCP (remoto) + Telegram.

Prueba automaticamente los dos tipos de conexion MCP (SSE y HTTP)
para no depender de adivinar cual usa FitMCP.
"""

import os
import sys
import asyncio
import datetime as dt

import requests
from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------

MODEL = "gemini-2.5-flash"

# .strip() elimina espacios o saltos de linea invisibles al copiar y pegar.
FITMCP_URL = os.environ["FITMCP_URL"].strip()

SYSTEM_PROMPT = "\n".join([
    "Eres el entrenador personal y analista de datos de Antonio.",
    "Cada manana analizas sus metricas de Garmin y le escribes un mensaje",
    "breve, directo y accionable, en espanol.",
    "",
    "PERFIL",
    "- Corredor de fondo, 4-5 sesiones por semana.",
    "- Objetivo: media maraton en una hora y media (ritmo 4:30 por km).",
    "- Ritmo objetivo de maraton: 4:45 por km.",
    "- Umbral de lactato: 177 pulsaciones por minuto.",
    "- Trabajo de oficina, horario estandar, base en Madrid.",
    "",
    "REGLAS",
    "- Usa SIEMPRE las herramientas de FitMCP. Nunca inventes cifras.",
    "- Si una herramienta falla o no devuelve dato, escribe 'sin dato'.",
    "- Compara cada metrica con la media de los ultimos 7 dias.",
    "- Prioriza: recuperacion, luego carga acumulada, luego sesion del dia.",
    "- Si hay senales de fatiga (HRV bajo, frecuencia cardiaca en reposo",
    "  elevada, sueno menor de 6 horas, carga aguda disparada), dilo sin",
    "  rodeos y recomienda bajar intensidad.",
    "- Maximo 250 palabras. Texto plano, sin tablas ni markdown.",
    "- Termina SIEMPRE con 'Sesion recomendada hoy:' y una propuesta",
    "  concreta: tipo de sesion, duracion y ritmo o zona objetivo.",
])

PROMPT = "\n".join([
    "Dame el informe de hoy. Consulta:",
    "1. Sueno de anoche: duracion, fases y puntuacion.",
    "2. HRV, frecuencia cardiaca en reposo y Body Battery de esta manana.",
    "3. Actividades de ayer: distancia, ritmo, frecuencia cardiaca media,",
    "   zonas y training effect.",
    "4. Carga de entrenamiento aguda frente a cronica de los ultimos 7 dias.",
    "5. Nivel de estres y pasos de ayer.",
])


# ---------------------------------------------------------------------------
# LOGICA
# ---------------------------------------------------------------------------

async def preguntar_a_gemini(sesion):
    cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    await sesion.initialize()

    herramientas = await sesion.list_tools()
    print("Herramientas de FitMCP disponibles:")
    for t in herramientas.tools:
        print("  - " + t.name)

    respuesta = await cliente.aio.models.generate_content(
        model=MODEL,
        contents=PROMPT,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[sesion],
            temperature=0.4,
        ),
    )
    texto = (respuesta.text or "").strip()
    return texto or "Sin resultado del modelo."


async def intentar_sse():
    async with sse_client(FITMCP_URL, timeout=60) as (read, write):
        async with ClientSession(read, write) as sesion:
            return await preguntar_a_gemini(sesion)


async def intentar_http():
    async with streamablehttp_client(FITMCP_URL) as (read, write, _):
        async with ClientSession(read, write) as sesion:
            return await preguntar_a_gemini(sesion)


async def generar_informe():
    errores = []

    for nombre, funcion in [("SSE", intentar_sse), ("HTTP", intentar_http)]:
        try:
            print("Probando conexion por " + nombre + "...")
            resultado = await funcion()
            print("Conexion por " + nombre + " correcta.")
            return resultado
        except Exception as e:
            aviso = nombre + " fallo: " + type(e).__name__ + ": " + str(e)
            print(aviso)
            errores.append(aviso)

    raise RuntimeError("Los dos metodos fallaron.\n" + "\n".join(errores))


def enviar_telegram(texto):
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    datos = {
        "chat_id": os.environ["TELEGRAM_CHAT_ID"].strip(),
        "text": texto,
        "disable_web_page_preview": True,
    }
    requests.post(url, json=datos, timeout=30).raise_for_status()


def main():
    hoy = dt.date.today().isoformat()
    try:
        informe = asyncio.run(generar_informe())
    except Exception as e:
        informe = (
            "[ERROR " + hoy + "] No se pudo generar el informe de Garmin.\n"
            + type(e).__name__ + ": " + str(e)
        )

    print("---- INFORME ----")
    print(informe)

    if "--dry-run" in sys.argv:
        return

    try:
        enviar_telegram(informe)
        print("Enviado por Telegram correctamente.")
    except Exception as e:
        print("Fallo al enviar por Telegram: " + str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
