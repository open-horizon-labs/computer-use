FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-tk xvfb x11vnc novnc websockify fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY vnc_fixture.py /fixture.py
ENV DISPLAY=:99
CMD ["sh", "-c", "Xvfb :99 -screen 0 1000x700x24 -ac & sleep 1; x11vnc -display :99 -rfbport 5900 -localhost -nopw -forever -shared >/tmp/vnc.log 2>&1 & websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 & exec python3 /fixture.py"]
