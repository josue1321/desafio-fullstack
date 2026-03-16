export class CreateWeatherDto {
  timezone: string;
  dt?: number;
  sunrise?: number;
  sunset?: number;
  temp?: number;
  feelsLike?: number;
  pressure?: number;
  humidity?: number;
  dewPoint?: number;
  uvi?: number;
  clouds?: number;
  visibility?: number;
  windSpeed?: number;
  windDeg?: number;
  weatherDescription: string;
  weatherMain: string;
  pop?: number;
}
