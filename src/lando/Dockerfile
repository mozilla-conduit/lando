FROM python:3.12
EXPOSE 80
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE 1

COPY requirements.txt /requirements.txt

RUN mkdir /code
WORKDIR /code
COPY ./lando /code
RUN pip install --upgrade pip
RUN pip install -r /requirements.txt
CMD ["bash"]
