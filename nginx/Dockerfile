FROM nginx:latest

WORKDIR /ssl
VOLUME /ssl

RUN openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
    -subj "/C=/ST=/L=/O=Lando/CN=lando.local" \
        -keyout /ssl/private.key  -out /ssl/certificate.crt

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
