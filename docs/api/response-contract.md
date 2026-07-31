# API 响应契约

成功响应：

```json
{
  "data": {},
  "meta": {
    "request_id": "8ae28fe6-700a-4f98-a18d-28c1ee5953c9"
  }
}
```

失败响应：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request",
    "details": []
  },
  "meta": {
    "request_id": "8ae28fe6-700a-4f98-a18d-28c1ee5953c9"
  }
}
```

客户端可传入合法 UUID 格式的 `X-Request-ID`；服务端会拒绝过长或非 UUID 值并生成新值。响应头和响应体返回同一标识。TypeScript 客户端将非 2xx 响应转换为包含状态码、错误码、请求标识和详情的 `ApiError`。

