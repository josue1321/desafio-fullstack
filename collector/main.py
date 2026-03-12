import os
import time
import sched
import httpx
import pika
import json
import logging


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
def send_to_queue(function, key, channel, queue):
    data = function(key)

    if data is None:
        logging.warning("No data fetched, skipping queue publish.")
        return

    try:
        message = json.dumps(data)

        channel.basic_publish(
            exchange="",
            routing_key=queue,
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

            return channel
        except pika.exceptions.AMQPConnectionError as e:
            logging.error(f"Error trying to connect: {e}")
            time.sleep(0.1)


def main():
    apiKey = os.getenv("WEATHER_API_KEY")
    rabbitmq_url = os.getenv("RABBITMQ_URL")
    rabbitmq_queue_name = os.getenv("RABBITMQ_QUEUE")
    interval = int(os.getenv("SEND_INTERVAL") or 3600)

    scheduler = sched.scheduler(time.time, time.sleep)

    channel = connect_to_rabbitmq(rabbitmq_url, interval)
    channel.queue_declare(queue=rabbitmq_queue_name, durable=True)

    repeat_after_interval(
        scheduler,
        interval,
        send_to_queue,
        (get_weather, apiKey, channel, rabbitmq_queue_name),
    )
    scheduler.run()


if __name__ == "__main__":
    main()
