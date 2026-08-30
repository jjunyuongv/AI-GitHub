import { useEffect, useState } from "react";
import { fetchMyRepos, type AuthStatus, type RepoList as RepoListData } from "./api";

type Props = {
  status: AuthStatus | null;
  /** 분석이 돌고 있는 동안 또 누르지 못하게 한다. */
  disabled: boolean;
  onPick: (url: string) => void;
};

/** 로그인한 사람의 공개 저장소 목록. 누르면 그 저장소로 분석을 시작한다.
 *
 * **로그인이 꺼져 있거나 안 했으면 아무것도 그리지 않는다.** 입력창을 대체하지 않는다 —
 * 조직(org) 소유 저장소·남의 저장소는 이 목록에 없고 입력창으로 간다.
 *
 * 마운트할 때마다 서버에 새로 묻는다. 캐시가 없으니 저장소를 새로 만들면 다음
 * 화면 로드에 바로 보인다.
 */
export default function RepoList({ status, disabled, onPick }: Props) {
  const login = status?.enabled ? status.user?.login : undefined;
  const [data, setData] = useState<RepoListData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!login) return;
    let alive = true;
    fetchMyRepos()
      .then((body) => alive && setData(body))
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "알 수 없는 오류가 발생했습니다");
      });
    return () => {
      alive = false;
    };
  }, [login]);

  if (!login) return null;

  if (error) return <p className="repo-list-note">{error}</p>;
  if (!data) return <p className="repo-list-note">저장소 목록을 불러오는 중…</p>;
  if (data.repos.length === 0) {
    return <p className="repo-list-note">분석할 수 있는 공개 저장소가 없습니다.</p>;
  }

  // 빈 저장소는 서버가 뺐고, 100개를 넘으면 최근 push 순으로 잘렸다 — 둘 다 total 과
  // 목록 길이의 차이로 드러난다.
  const shown = data.repos.length;
  const head = data.total > shown
    ? `공개 저장소 ${shown}개 (전체 ${data.total}개 중 최근 push 순)`
    : `공개 저장소 ${shown}개`;

  return (
    <section className="repo-list">
      <h2>{head}</h2>
      <p className="repo-list-note">
        빈 저장소는 빠져 있습니다. 여기 없는 저장소(조직 소유 등)는 위 입력창에 주소를 넣으세요.
      </p>
      <ul>
        {data.repos.map((repo) => (
          <li key={`${repo.owner}/${repo.name}`}>
            <button
              type="button"
              className="repo-row"
              disabled={disabled || repo.too_large}
              onClick={() => onPick(repo.html_url)}
            >
              <span className="repo-row-head">
                <strong>{repo.name}</strong>
                {repo.fork && <span className="badge">포크</span>}
                {repo.archived && <span className="badge">보관됨</span>}
                {repo.too_large && <span className="badge too-large">너무 큽니다</span>}
              </span>
              {repo.description && <span className="repo-row-desc">{repo.description}</span>}
              <span className="repo-row-meta">
                {repo.language && <span>{repo.language}</span>}
                <span>{formatSize(repo.size_kb)}</span>
                <span>{formatDate(repo.pushed_at)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatSize(kb: number): string {
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}
