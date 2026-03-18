import * as z from 'zod';

export const createWeatherSchema = z
  .object({
    timezone: z.string(),
    dt: z.number(),
    sunrise: z.number(),
    sunset: z.number(),
    temp: z.number(),
    feelsLike: z.number(),
    pressure: z.number(),
    humidity: z.number(),
    dewPoint: z.number(),
    uvi: z.number(),
    clouds: z.number(),
    visibility: z.number(),
    windSpeed: z.number(),
    windDeg: z.number(),
    weatherDescription: z.string(),
    weatherMain: z.string(),
    pop: z.number(),
  })
  .required();

export type CreateWeatherDto = z.infer<typeof createWeatherSchema>;
