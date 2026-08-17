import "./pagination-controls.css";

type PaginationControlsProps = {
  isLoading?: boolean;
  onPageChange: (page: number) => void | Promise<void>;
  page: number;
  pageSize: number;
  totalCount: number;
  totalPages: number;
};

export function PaginationControls({
  isLoading = false,
  onPageChange,
  page,
  pageSize,
  totalCount,
  totalPages,
}: PaginationControlsProps) {
  const firstItem = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastItem = Math.min(page * pageSize, totalCount);
  const canGoBack = page > 1 && !isLoading;
  const canGoForward = page < totalPages && !isLoading;

  return (
    <nav className="pagination-controls" aria-label="分页导航">
      <span className="pagination-controls__summary">
        {firstItem}-{lastItem} / {totalCount}
      </span>
      <div className="pagination-controls__actions">
        <button type="button" disabled={!canGoBack} onClick={() => onPageChange(1)}>首页</button>
        <button type="button" disabled={!canGoBack} onClick={() => onPageChange(page - 1)}>上一页</button>
        <span>{isLoading ? "加载中" : `第 ${page} / ${totalPages} 页`}</span>
        <button type="button" disabled={!canGoForward} onClick={() => onPageChange(page + 1)}>下一页</button>
        <button type="button" disabled={!canGoForward} onClick={() => onPageChange(totalPages)}>末页</button>
      </div>
    </nav>
  );
}
