#!/usr/bin/env python3
"""
Servidor simple para el Panel de Trading Manual
Sirve el archivo HTML y redirige llamadas API a Freqtrade
"""

import http.server
import socketserver
import requests
import os
from urllib.parse import urlparse, parse_qs
import json

PORT = 8090
FREQTRADE_API = "http://localhost:8080/api/v1"
AUTH = (
    os.getenv("FREQTRADE_API_USER", "admin"),
    os.getenv("FREQTRADE_API_PASSWORD", ""),
)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # API proxy para Freqtrade
        if self.path.startswith('/api/'):
            try:
                url = FREQTRADE_API + self.path.replace('/api/', '/')
                resp = requests.get(url, auth=AUTH, timeout=5)
                self.send_response(resp.status_code)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(resp.content)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
        
        # Servir el archivo HTML
        if self.path == '/' or self.path == '/index.html':
            self.path = '/user_data/manual_trading.html'
        return http.server.SimpleHTTPRequestHandler.do_GET(self)
    
    def do_POST(self):
        # API proxy para Freqtrade POST
        if self.path.startswith('/api/'):
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)
                url = FREQTRADE_API + self.path.replace('/api/', '/')
                
                headers = {'Content-Type': 'application/json'}
                resp = requests.post(url, auth=AUTH, data=body, headers=headers, timeout=5)
                
                self.send_response(resp.status_code)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(resp.content)
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return
        
        self.send_response(404)
        self.end_headers()
    
    def log_message(self, format, *args):
        # Silenciar logs de requests
        pass

if __name__ == '__main__':
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"🤖 Panel de Trading Manual iniciado")
        print(f"🌐 URL: http://localhost:{PORT}")
        print(f"📊 Freqtrade API: localhost:8080")
        print(f"\n✨ Abre tu navegador y ve a: http://localhost:{PORT}")
        print(f"⚠️  No cierres esta ventana mientras uses el panel\n")
        httpd.serve_forever()
