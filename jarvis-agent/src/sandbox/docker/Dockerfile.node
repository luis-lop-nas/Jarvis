# Dockerfile.node
# Imagen base para ejecutar código Node.js en sandbox

FROM node:20-slim

# Instalamos algunas librerías comunes de Node
# (puedes añadir más según necesites)
RUN npm install -g \
    lodash \
    axios \
    moment

# Directorio de trabajo donde se montará el workspace
WORKDIR /workspace

# Usuario no-root para seguridad
RUN useradd -m -u 1000 jarvis && \
    chown -R jarvis:jarvis /workspace

USER jarvis

# Por defecto ejecuta node (se le pasa el script como argumento)
ENTRYPOINT ["node"]