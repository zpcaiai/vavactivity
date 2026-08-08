export interface PageResult<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}
