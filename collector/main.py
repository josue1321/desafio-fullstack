import os
import time
import sched
import httpx
import pika
import json
import logging
import signal
import sys


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def get_weather(appId):
    try:
        response_obj = httpx.get(
            f"https://api.openweathermap.org/data/3.0/onecall?lat=33.44&lon=-94.04&appid={appId}",
            timeout=10.0,
        )

        response_obj.raise_for_status()
        response = response_obj.json()
    except httpx.RequestError as e:
        logging.error(f"Network error occurred: {e}")
        return None
    except httpx.HTTPStatusError as e:
        logging.error(f"API error: {e}")
        return None
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON response")
        return None

    keysToExtract = {
        "timezone": None,
        "current": {},
        "weather": {"main", "description"},
        "hourly": {"pop"},
    }

    weather = {}

    for key in keysToExtract.copy():
        if key in response and key in keysToExtract:
            try:
                if type(keysToExtract[key]) is type(None):
                    weather[key] = response[key]
                elif type(keysToExtract[key]) is type({}):
                    for field in response[key]:
                        if type(response[key][field]) is type([]):
                            if field in keysToExtract:
                                subfields = keysToExtract.pop(field)

                                for subfield in subfields:
                                    weather[f"{field}_{subfield}"] = response[key][
                                        field
                                    ][0][subfield]
                        else:
                            weather[field] = response[key][field]
                else:
                    if len(response[key]) > 0:
                        for field in keysToExtract[key]:
                            weather[field] = response[key][0][field]
            except (KeyError, IndexError, TypeError) as e:
                logging.error(f"Error parsing data for key {key}: {e}")

    return weather


# make it send only if the last message was sent more than 1 hour ago
def send_to_queue(function, key, channel, exchange, routing_key):
    data = function(key)

    if data is None:
        logging.warning("No data fetched, skipping queue publish.")
        return

    try:
        message = json.dumps(data)

        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=message,
            properties=pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent),
        )

        logging.info(" [*] Message published to the queue")
    except pika.exceptions.AMQPError as e:
        logging.error(f"RabbitMQ Error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error publishing: {e}")


def repeat_after_interval(scheduler, interval, action, args=()):
    try:
        action(*args)
    except Exception as e:
        logging.error(f"Job failed, but rescheduling: {e}")

    scheduler.enter(
        interval, 1, repeat_after_interval, (scheduler, interval, action, args)
    )


def connect_to_rabbitmq(rabbitmq_url, rabbitmq_heartbeat):
    while True:
        try:
            parameters = pika.URLParameters(
                f"{rabbitmq_url}?heartbeat={rabbitmq_heartbeat}"
            )

            connection = pika.BlockingConnection(parameters=parameters)
            channel = connection.channel()

            return connection, channel
        except pika.exceptions.AMQPConnectionError as e:
            logging.error(f"Error trying to connect: {e}")
            time.sleep(0.1)


def handle_sigterm(*args):
    raise KeyboardInterrupt()


def main():
    signal.signal(signal.SIGTERM, handle_sigterm)

    apiKey = os.getenv("WEATHER_API_KEY")
    rabbitmq_url = os.getenv("RABBITMQ_URL")
    rabbitmq_queue_name = os.getenv("RABBITMQ_QUEUE")
    rabbitmq_retry_queue_name = f"{rabbitmq_queue_name}.retry"
    rabbitmq_exchange_name = os.getenv("RABBITMQ_EXCHANGE") or "weather.exchange"
    rabbitmq_retry_exchange_name = f"{rabbitmq_exchange_name}.retry"
    rabibitmq_routing_key = os.getenv("RABBITMQ_ROUTING_KEY")
    interval = int(os.getenv("SEND_INTERVAL") or 3600)

    scheduler = sched.scheduler(time.time, time.sleep)

    connection, channel = connect_to_rabbitmq(rabbitmq_url, interval)

    channel.exchange_declare(
        exchange=rabbitmq_exchange_name, exchange_type="direct", durable=True
    )
    channel.exchange_declare(
        exchange=rabbitmq_retry_exchange_name, exchange_type="direct", durable=True
    )

    retry_args = {
        "x-dead-letter-exchange": rabbitmq_exchange_name,
        "x-dead-letter-routing-key": rabibitmq_routing_key,
        "x-message-ttl": 10000,
    }

    channel.queue_declare(
        queue=rabbitmq_retry_queue_name, durable=True, arguments=retry_args
    )

    channel.queue_bind(
        queue=rabbitmq_retry_queue_name,
        exchange=rabbitmq_retry_exchange_name,
        routing_key=rabibitmq_routing_key,
    )

    main_args = {
        "x-dead-letter-exchange": rabbitmq_retry_exchange_name,
        "x-dead-letter-routing-key": rabibitmq_routing_key,
    }

    channel.queue_declare(queue=rabbitmq_queue_name, durable=True, arguments=main_args)

    channel.queue_bind(
        queue=rabbitmq_queue_name,
        exchange=rabbitmq_exchange_name,
        routing_key=rabibitmq_routing_key,
    )

    repeat_after_interval(
        scheduler,
        interval,
        send_to_queue,
        (get_weather, apiKey, channel, rabbitmq_exchange_name, rabibitmq_routing_key),
    )

    try:
        logging.info("Starting scheduler")
        scheduler.run()
    except KeyboardInterrupt:
        logging.info("Shutting down")
    finally:
        if connection and connection.is_open:
            connection.close()
            logging.info("RabbitMQ connection gracefully closed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
