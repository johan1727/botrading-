"""Prueba rápida de Groq y OpenRouter APIs"""
import json

# Test Groq key 1
try:
    from groq import Groq
    client = Groq(api_key="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")
    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": 'Solo JSON: {"accion":"BUY","confianza":75,"razon":"test ok"}'}],
        max_tokens=50
    )
    print("GROQ-1 OK:", r.choices[0].message.content[:80])
except Exception as e:
    print("GROQ-1 ERROR:", str(e)[:120])

# Test Groq key 2
try:
    from groq import Groq
    client2 = Groq(api_key="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")
    r2 = client2.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": 'Solo JSON: {"accion":"BUY","confianza":75,"razon":"test ok"}'}],
        max_tokens=50
    )
    print("GROQ-2 OK:", r2.choices[0].message.content[:80])
except Exception as e:
    print("GROQ-2 ERROR:", str(e)[:120])

# Test OpenRouter key
try:
    import urllib.request
    data = json.dumps({
        "model": "meta-llama/llama-3.2-3b-instruct:free",
        "messages": [{"role": "user", "content": 'Solo JSON: {"accion":"BUY","confianza":75,"razon":"test ok"}'}],
        "max_tokens": 50
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data,
        headers={
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    print("OPENROUTER OK:", result["choices"][0]["message"]["content"][:80])
except Exception as e:
    print("OPENROUTER ERROR:", str(e)[:120])

# Listar modelos gratuitos de OpenRouter disponibles
try:
    import urllib.request
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": "Bearer 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"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        models = json.loads(resp.read())
    free_models = [m["id"] for m in models["data"] if ":free" in m["id"]]
    print(f"\nOpenRouter modelos GRATIS ({len(free_models)}):")
    for m in free_models[:15]:
        print(" -", m)
except Exception as e:
    print("OPENROUTER MODELS ERROR:", str(e)[:120])
