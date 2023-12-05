FROM python:3.12

EXPOSE 80
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE 1
RUN adduser --system --no-create-home app
RUN mkdir /code
COPY ./ /code
RUN pip install --upgrade pip
RUN pip install -r /code/requirements.txt
RUN pip install -e /code
USER app

CMD ["bash"]
