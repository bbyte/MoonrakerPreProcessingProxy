import yaml
import httpx
import uvicorn
from fastapi import FastAPI, UploadFile, Request
from fastapi.responses import StreamingResponse
import importlib.util
import sys
from pathlib import Path
from datetime import datetime
import json
from urllib.parse import parse_qs

app = FastAPI()

# Load configuration
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

MOONRAKER_URL = config["moonraker"]["url"]
PROXY_HOST = config["proxy"]["host"]
PROXY_PORT = config["proxy"]["port"]
DEBUG = config["proxy"].get("debug", False)

def log_debug(message: str):
    """Print debug message if debug mode is enabled."""
    if DEBUG:
        print(f"[DEBUG] {datetime.now().isoformat()} - {message}")

def log_info(message: str):
    """Print info message."""
    print(f"[INFO] {datetime.now().isoformat()} - {message}")

def log_error(message: str, error: Exception = None):
    """Print error message with optional exception details."""
    print(f"[ERROR] {datetime.now().isoformat()} - {message}")
    if error and DEBUG:
        print(f"[ERROR] Stack trace: {str(error)}")

async def log_request_details(request: Request, body: bytes = None):
    """Log detailed request information when debug is enabled."""
    if DEBUG:
        headers = dict(request.headers)
        query_params = dict(request.query_params)
        
        log_data = {
            "method": request.method,
            "url": str(request.url),
            "client": request.client.host if request.client else "unknown",
            "headers": headers,
            "query_params": query_params,
        }
        
        if body:
            try:
                log_data["body"] = body.decode() if len(body) < 1024 else f"<{len(body)} bytes>"
            except:
                log_data["body"] = f"<{len(body)} bytes binary data>"
        
        log_debug(f"Request details: {json.dumps(log_data, indent=2)}")

async def load_and_execute_rule(rule_path: str, file_path: Path):
    """Load and execute a preprocessing rule on the uploaded file."""
    try:
        log_info(f"Executing rule: {rule_path} on file: {file_path}")
        spec = importlib.util.spec_from_file_location("rule", rule_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules["rule"] = module
            spec.loader.exec_module(module)
            if hasattr(module, "process"):
                log_debug(f"Starting processing with rule: {rule_path}")
                await module.process(file_path)
                log_debug(f"Completed processing with rule: {rule_path}")
            else:
                print(f"[WARNING] Rule {rule_path} has no process function")
    except Exception as e:
        log_error(f"Error executing rule {rule_path}", e)

@app.api_route("/{path:path}", methods=["POST"])
async def proxy_post(request: Request, path: str):
    """Handle POST requests, with special handling for file uploads."""
    body = await request.body()
    await log_request_details(request, body)
    
    content_type = request.headers.get("content-type", "")
    log_info(f"Handling POST request to path: {path}")
    
    # Check if this is a file upload request to /api/files/local
    if path == "api/files/local":
        log_info("Detected file upload request to /api/files/local")
        try:
            # Parse the multipart form data
            form = await request.form()
            log_debug(f"Form fields: {list(form.keys())}")
            
            # Get the file from the form
            file = form.get("file")
            if not file:
                raise ValueError("No file found in upload request")
                
            filename = file.filename
            content = await file.read()
            
            log_info(f"Processing uploaded file: {filename}")
            
            # Save the uploaded file temporarily
            temp_path = Path(f"/tmp/{filename}")
            with open(temp_path, "wb") as temp_file:
                temp_file.write(content)
            log_debug(f"Saved temporary file to: {temp_path}")

            # Execute preprocessing rules
            rules_executed = 0
            for rule in config["preprocessing_rules"]:
                if rule["enabled"]:
                    log_info(f"Executing rule {rule['name']}")
                    await load_and_execute_rule(rule["script"], temp_path)
                    rules_executed += 1
            
            # Log the number of rules executed  
            log_info(f"Executed {rules_executed} preprocessing rules")

            # Upload processed file to Moonraker
            log_info(f"Uploading processed file to Moonraker: {filename}")
            async with httpx.AsyncClient() as client:
                # Create form data with original file name
                files = {
                    "file": (filename, open(temp_path, "rb"), "application/octet-stream")
                }
                # Forward any additional form fields from the original request
                data = {
                    key: value for key, value in form.items()
                    if key != "file"
                }
                
                response = await client.post(
                    f"{MOONRAKER_URL}/{path}",
                    files=files,
                    data=data
                )
                temp_path.unlink()  # Clean up temporary file
                log_debug(f"Moonraker response status: {response.status_code}")
                if DEBUG:
                    log_debug(f"Moonraker response headers: {dict(response.headers)}")
                    if response.status_code >= 400:
                        log_debug(f"Moonraker error response: {response.text}")
                return StreamingResponse(
                    content=response.iter_bytes(),
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )

        except Exception as e:
            log_error("Error processing file upload", e)
            return StreamingResponse(
                content=iter([str(e).encode()]),
                status_code=500
            )

    # For non-file-upload requests, pass through directly
    log_debug(f"Passing through request to Moonraker: {path}")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{MOONRAKER_URL}/{path}",
            content=body,
            headers=request.headers,
            params=dict(request.query_params)
        )
        log_debug(f"Moonraker response status: {response.status_code}")
        return StreamingResponse(
            content=response.iter_bytes(),
            status_code=response.status_code,
            headers=dict(response.headers)
        )

@app.api_route("/{path:path}", methods=["GET", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, path: str):
    """Handle all other HTTP methods by passing through to Moonraker."""
    body = await request.body()
    await log_request_details(request, body)
    
    log_debug(f"Proxying {request.method} request to: {path}")
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=request.method,
            url=f"{MOONRAKER_URL}/{path}",
            content=body,
            headers=request.headers,
            params=dict(request.query_params)
        )
        log_debug(f"Moonraker response status: {response.status_code}")
        return StreamingResponse(
            content=response.iter_bytes(),
            status_code=response.status_code,
            headers=dict(response.headers)
        )

if __name__ == "__main__":
    log_info(f"Starting Moonraker Preprocessing Proxy on {PROXY_HOST}:{PROXY_PORT}")
    log_info(f"Debug mode: {'enabled' if DEBUG else 'disabled'}")
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT)
