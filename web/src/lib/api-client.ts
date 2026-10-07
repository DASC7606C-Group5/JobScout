import axios from 'axios'
import { parse, ValiError, type GenericSchema } from 'valibot'

import type { paths } from '../api/openapi.gen'
import {
  applicantErrorAction,
  applicantErrorMessage,
  ApplicantRequestError,
  responseErrorCode,
  type ApplicantErrorCode,
} from './applicant-errors'

export type ApiFetcher = (url: string, init: RequestInit) => Promise<Response>
type Method = 'get' | 'post' | 'put' | 'delete'
type Endpoint<M extends Method> = {
  [P in keyof paths]: paths[P][M] extends undefined ? never : P
}[keyof paths]
type Operation<P extends keyof paths, M extends Method> = NonNullable<paths[P][M]>
type RequestOptions<O> = { signal?: AbortSignal } & (O extends { parameters: { path: infer P } }
  ? { path: P }
  : { path?: never }) &
  (O extends { parameters: { query?: infer Q } } ? { query?: Q } : { query?: never }) &
  (O extends { requestBody: { content: { 'application/json': infer B } } }
    ? { body: B }
    : { body?: FormData })

export class SessionHttpError extends Error {
  constructor(
    public status: number,
    public code: ApplicantErrorCode,
  ) {
    super(applicantErrorMessage(code, status))
    this.name = 'SessionHttpError'
  }
  get action() {
    return applicantErrorAction(this.code, this.status)
  }
}

export function createApiClient(
  baseUrl: string,
  fetcher: ApiFetcher,
  failure: (status: number, data: unknown) => Error = (status, data) =>
    new SessionHttpError(status, responseErrorCode(data, status)),
) {
  const client = axios.create({
    baseURL: baseUrl.replace(/\/+$/, ''),
    headers: { Accept: 'application/json' },
    paramsSerializer: { encode: encodeURIComponent },
    // Keep account cancellation and CSRF in the existing authenticated transport.
    adapter: async (config) => {
      const body: unknown = config.data
      const headers = new Headers()
      Object.entries(config.headers.toJSON()).forEach(([key, value]) => {
        if (value !== null && value !== undefined) headers.set(key, String(value))
      })
      if (body instanceof FormData) headers.delete('Content-Type')
      let response: Response
      try {
        response = await fetcher(client.getUri(config), {
          method: (config.method ?? 'GET').toUpperCase(),
          headers,
          ...(typeof body === 'string' || body instanceof FormData ? { body } : {}),
          ...(config.signal ? { signal: config.signal as AbortSignal } : {}),
        })
      } catch (error) {
        if (
          config.signal?.aborted ||
          (error instanceof DOMException && error.name === 'AbortError')
        )
          throw error
        throw new ApplicantRequestError('connection_unavailable')
      }
      return {
        data: await response.text(),
        status: response.status,
        statusText: response.statusText,
        headers: Object.fromEntries(response.headers),
        config,
      }
    },
  })
  client.interceptors.response.use((response) => {
    if (response.status < 200 || response.status >= 300)
      throw failure(response.status, response.data)
    return response
  })

  async function request<M extends Method, P extends Endpoint<M>, T>(
    method: M,
    endpoint: P,
    options: RequestOptions<Operation<P, M>>,
    schema?: GenericSchema<T>,
  ): Promise<T> {
    options.signal?.throwIfAborted()
    const supplied = options as {
      path?: Record<string, string | number>
      query?: unknown
      body?: unknown
      signal?: AbortSignal
    }
    const url = endpoint.replace(/\{([^}]+)\}/g, (_, name: string) =>
      encodeURIComponent(String(supplied.path?.[name])),
    )
    try {
      const response = await client.request<unknown>({
        url: url.slice('/api/v1'.length),
        method,
        ...(supplied.body === undefined ? {} : { data: supplied.body }),
        ...(supplied.query === undefined ? {} : { params: supplied.query }),
        ...(options.signal ? { signal: options.signal } : {}),
      })
      options.signal?.throwIfAborted()
      return schema ? parse(schema, response.data) : (undefined as T)
    } catch (error) {
      options.signal?.throwIfAborted()
      if (error instanceof ValiError || error instanceof SyntaxError)
        throw new ApplicantRequestError('invalid_response')
      throw error
    }
  }
  return { request, axios: client }
}
