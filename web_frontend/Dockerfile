FROM nginx:1.27-alpine

COPY web_frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY web_frontend/index.html /usr/share/nginx/html/index.html
COPY web_frontend/styles.css /usr/share/nginx/html/styles.css
COPY web_frontend/app.js /usr/share/nginx/html/app.js

EXPOSE 80
