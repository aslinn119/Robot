"""Local mock coordinator; role tokens must be supplied through environment."""
import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from network_v1.managed import ManagedCoordinator
from threading import Event, Thread
from network_v1.transport import ProtocolError
from network_v1.transport import create_server


def main():
    parser = argparse.ArgumentParser(description='Roban protocol 1.0 mock coordinator')
    parser.add_argument('--port', type=int, default=8780)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--enable-robot', action='store_true', help='Allow robot sessions after readiness checks; motion remains disabled')
    args = parser.parse_args()
    tokens = {r: os.environ.get('ROBAN_TOKEN_' + r, '') for r in 'ABCD'}
    if not all(tokens.values()) or len(set(tokens.values())) != 4:
        parser.error('Set four distinct ROBAN_TOKEN_A/B/C/D environment variables first.')
    try:
        coordinator = ManagedCoordinator(tokens, Path(__file__).resolve().parents[1] / 'runtime' / 'network_private', enable_robot=args.enable_robot)
    except (ValueError, OSError, KeyError, TypeError):
        parser.error('Cannot load network journal. Check runtime/network_private/network_private.json; original data is preserved.')
    server = create_server(coordinator, args.port, args.host)
    stop = Event()
    def deadlines():
        while not stop.wait(0.25):
            try:
                coordinator.tick()
            except ProtocolError as error:
                print('Deadline journal unavailable:', error.code)
    worker = Thread(target=deadlines, daemon=True)
    worker.start()
    print('Referee: http://%s:%s (robot_enabled=%s; motion disabled)' % (args.host,server.server_port,args.enable_robot))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join(timeout=2)
        server.server_close()


if __name__ == '__main__':
    main()
