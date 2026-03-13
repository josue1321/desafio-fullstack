package main

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	amqp "github.com/rabbitmq/amqp091-go"
)

type WeatherData struct {
	Timezone           string   `json:"timezone"`
	Dt                 *int64   `json:"dt"`
	Sunrise            *int64   `json:"sunrise"`
	Sunset             *int64   `json:"sunset"`
	Temp               *float64 `json:"temp"`
	FeelsLike          *float64 `json:"feels_like"`
	Pressure           *int     `json:"pressure"`
	Humidity           *int     `json:"humidity"`
	DewPoint           *float64 `json:"dew_point"`
	Uvi                *float64 `json:"uvi"`
	Clouds             *int     `json:"clouds"`
	Visibility         *int     `json:"visibility"`
	WindSpeed          *float64 `json:"wind_speed"`
	WindDeg            *int     `json:"wind_deg"`
	WeatherDescription string   `json:"weather_description"`
	WeatherMain        string   `json:"weather_main"`
	Pop                *float64 `json:"pop"`
}

func failOnError(err error, msg string) {
	if err != nil {
		log.Fatalf("%s: %s", msg, err)
	}
}

func printOnError(err error, msg string) {
	if err != nil {
		log.Printf("%v: %v", msg, err)
	}
}

func processMessage(msg amqp.Delivery, apiURL string) {
	if getRetryCount(msg) >= 6 {
		log.Printf("Message has failed 6 times. Dropping permanently: %s", string(msg.Body))
		msg.Ack(false)
		return
	}

	if !json.Valid(msg.Body) {
		log.Printf("Error: Message JSON is not valid. Body: %s", string(msg.Body))
		printOnError(msg.Nack(false, false), "Failed to negative acknowledge the message")
		return
	}

	var weather WeatherData

	if err := json.Unmarshal(msg.Body, &weather); err != nil {
		log.Printf("Failed to unmarshal message: %v", err)
		printOnError(msg.Nack(false, false), "Failed to negative acknowledge the message")
		return
	}

	weatherJSON, err := json.Marshal(weather)
	if err != nil {
		log.Printf("Failed to marshal message: %v", err)
		printOnError(msg.Nack(false, false), "Failed to negative acknowledge the message")
		return
	}

	resp, err := http.Post(apiURL, "application/json", bytes.NewBuffer(weatherJSON))
	if err != nil {
		log.Printf("Failed to post the message to the api: %v", err)
		printOnError(msg.Nack(false, false), "Failed to negative acknowledge the message")
		return
	}

	defer resp.Body.Close()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		if err := msg.Ack(false); err != nil {
			log.Printf("Failed to acknowledge message: %v", err)
		}
	} else {
		log.Printf("API failed with status %d", resp.StatusCode)
		printOnError(msg.Nack(false, false), "Failed to negative acknowledge the message")
	}
}

func getRetryCount(msg amqp.Delivery) int64 {
	if msg.Headers == nil {
		return 0
	}

	xDeathArray, ok := msg.Headers["x-death"].([]any)
	if !ok || len(xDeathArray) == 0 {
		return 0
	}

	firstEntry, ok := xDeathArray[0].(amqp.Table)
	if !ok {
		return 0
	}

	count, ok := firstEntry["count"].(int64)
	if !ok {
		return 0
	}

	return count
}

func main() {
	rabbitmqURL := os.Getenv("RABBITMQ_URL")
	rabbitmqQueueName := os.Getenv("RABBITMQ_QUEUE")
	rabbitmqRetryQueueName := rabbitmqQueueName + ".retry"
	rabbitmqExchangeName := os.Getenv("RABBITMQ_EXCHANGE")
	rabbitmqRetryExchangeName := rabbitmqExchangeName + ".retry"
	rabbitmqRoutingKey := os.Getenv("RABBITMQ_ROUTING_KEY")

	apiURL := os.Getenv("API_URL")

	conn, err := amqp.Dial(rabbitmqURL)
	failOnError(err, "Failed to connect to RabbitMQ")

	defer conn.Close()

	ch, err := conn.Channel()
	failOnError(err, "Failed to open a channel")
	defer ch.Close()

	err = ch.ExchangeDeclare(
		rabbitmqExchangeName,
		"direct",
		true,
		false,
		false,
		false,
		nil,
	)
	failOnError(err, "Failed to declare main exchange")

	err = ch.ExchangeDeclare(
		rabbitmqRetryExchangeName,
		"direct",
		true,
		false,
		false,
		false,
		nil,
	)
	failOnError(err, "Failed to declare retry exchange")

	retryArgs := amqp.Table{
		"x-dead-letter-exchange":    rabbitmqExchangeName,
		"x-dead-letter-routing-key": rabbitmqRoutingKey,
		"x-message-ttl":             int32(10000),
	}

	_, err = ch.QueueDeclare(
		rabbitmqRetryQueueName,
		true,
		false,
		false,
		false,
		retryArgs,
	)
	failOnError(err, "Failed to declare retry queue")

	err = ch.QueueBind(
		rabbitmqRetryQueueName,
		rabbitmqRoutingKey,
		rabbitmqRetryExchangeName,
		false,
		nil,
	)
	failOnError(err, "Failed to bind retry queue and exchange")

	mainArgs := amqp.Table{
		"x-dead-letter-exchange":    rabbitmqRetryExchangeName,
		"x-dead-letter-routing-key": rabbitmqRoutingKey,
	}

	q, err := ch.QueueDeclare(
		rabbitmqQueueName,
		true,
		false,
		false,
		false,
		mainArgs,
	)
	failOnError(err, "Failed to declare main queue")

	err = ch.QueueBind(
		q.Name,
		rabbitmqRoutingKey,
		rabbitmqExchangeName,
		false,
		nil,
	)
	failOnError(err, "Failed to bind main queue and exchange")

	msgs, err := ch.Consume(
		q.Name,
		"",
		false,
		false,
		false,
		false,
		nil,
	)
	failOnError(err, "Failed to register consume")

	go func() {
		for msg := range msgs {
			processMessage(msg, apiURL)
		}
	}()

	log.Printf(" [*] Waiting for messages.")

	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	<-stopChan

	log.Println("Shutting down gracefully...")
}
