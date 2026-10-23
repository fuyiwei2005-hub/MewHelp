"""Run one independent mock MCP process; optional local developer plugin."""
import argparse,importlib.util
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--server',choices=['logistics','aftersales'],required=True)
    parser.add_argument('--port',type=int)
    parser.add_argument('--plugin-file',type=Path)
    args=parser.parse_args()
    if args.server=='logistics':
        from mcp_servers.logistics import create_server
        server=create_server(args.port or 18011)
    else:
        from mcp_servers.aftersales import create_server
        server=create_server(args.port or 18012)
    if args.plugin_file:
        spec=importlib.util.spec_from_file_location('local_mcp_extension',args.plugin_file.resolve())
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.register(server)
    server.run(transport='streamable-http')

if __name__=='__main__':main()
