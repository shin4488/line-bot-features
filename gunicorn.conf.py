# The bot does not use Gunicorn's optional control server. Disabling its
# background thread also avoids the worker respawn loop reproduced on macOS.
control_socket_disable = True
