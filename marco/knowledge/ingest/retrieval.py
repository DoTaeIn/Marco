"""Read-only web evidence, with source provenance and no automatic truth promotion.

The public backend performs real HTTP requests. Injected backends are always
labelled ``offline_fixture``. Source sentences and parsed triples remain
untrusted observations; this module never writes a graph or activates a fact.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import ipaddress
from itertools import islice
import json
import re
import socket
import ssl
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from . import web


class RetrievalError(ValueError):
    """A deliberately small error code; URLs/credentials are never error text."""


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _id(kind, *values):
    raw = json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
    return kind + "-" + hashlib.sha256(raw).hexdigest()[:20]


def _error(exc):
    reason = getattr(exc, "reason", exc)
    return {"type": type(exc).__name__, "code": str(exc) if isinstance(exc, RetrievalError)
            else "http_" + str(exc.code) if isinstance(exc, urllib.error.HTTPError)
            else "tls_certificate_verification_failed" if isinstance(reason, ssl.SSLCertVerificationError)
            else "timeout" if isinstance(exc, (TimeoutError, socket.timeout))
            else "connection_failed" if isinstance(exc, (OSError, urllib.error.URLError))
            else "invalid_response"}


def _tls_context():
    context = ssl.create_default_context()
    if context.cert_store_stats()["x509_ca"] == 0:
        # Some macOS Python installations omit their CA-file setup. Reuse an
        # already installed public CA bundle; never disable verification.
        try:
            import certifi
        except ImportError as exc:
            raise RetrievalError("tls_trust_store_unavailable") from exc
        context = ssl.create_default_context(cafile=certifi.where())
    return context


def public_url(url, *, resolve=False):
    """Reject non-web URLs, credentials, local literals and local DNS answers.

    HTTP redirects are checked through the same policy. This is a basic public
    source guard, not a guarantee against DNS rebinding or a network sandbox.
    """
    if not isinstance(url, str) or len(url) > 4096 or re.search(r"[\x00-\x20\x7f]", url):
        raise RetrievalError("invalid_url")
    try:
        parsed = urllib.parse.urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise RetrievalError("invalid_url") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        raise RetrievalError("public_http_url_required")
    if parsed.username is not None or parsed.password is not None:
        raise RetrievalError("url_credentials_forbidden")
    if port is not None and port not in {80, 443}:
        raise RetrievalError("nonstandard_port_forbidden")
    host = host.lower().rstrip(".")
    if (host == "localhost" or "." not in host and ":" not in host
            or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))):
        raise RetrievalError("private_host_forbidden")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise RetrievalError("private_address_forbidden")
    if resolve:
        try:
            addresses = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80),
                                          type=socket.SOCK_STREAM)
        except OSError as exc:
            raise RetrievalError("dns_failed") from exc
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise RetrievalError("private_dns_forbidden")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/",
                                   parsed.query, ""))


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 4

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl, resolve=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _decode_mediawiki_opensearch(body, count):
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, AttributeError) as exc:
        raise RetrievalError("search_malformed_json") from exc
    if isinstance(data, dict):
        raise RetrievalError("search_api_error")
    if type(data) is not list or len(data) != 4:
        raise RetrievalError("search_schema_invalid")
    query, titles, descriptions, urls = data
    if type(query) is not str or len(query) > 500:
        raise RetrievalError("search_schema_invalid")
    arrays = (titles, descriptions, urls)
    if any(type(a) is not list for a in arrays) or len({len(a) for a in arrays}) != 1:
        raise RetrievalError("search_schema_invalid")
    if len(urls) > count or len(urls) > 5:
        raise RetrievalError("search_schema_invalid")
    for item in titles + descriptions + urls:
        if type(item) is not str or len(item) > 4096:
            raise RetrievalError("search_schema_invalid")
    rows = []
    for link, title in zip(urls, titles):
        try:
            link = public_url(link)
        except RetrievalError as exc:
            raise RetrievalError("search_invalid_result_url") from exc
        rows.append({"url": link, "title": title})
    meta = {"protocol": "mediawiki_opensearch", "query_echo": query,
            "result_count": len(rows), "descriptions_ignored": True}
    return rows, meta


class PublicWebBackend:
    """No-key Bing RSS discovery and bounded public HTML/text fetching.

    Search snippets discover addresses only. Existing web.py sentence and role
    extraction is reused. Search providers can block automation; that is an
    explicit failure, never a switch to canned local results.
    """
    provider = "bing_public_rss"

    def __init__(self, *, timeout=5, max_bytes=512 * 1024,
                 provider="bing_public_rss", search_endpoint=None, user_agent=None):
        if type(timeout) not in {int, float} or not 0 < timeout <= 10:
            raise ValueError("invalid_timeout")
        if type(max_bytes) is not int or not 1024 <= max_bytes <= 2 * 1024 * 1024:
            raise ValueError("invalid_max_bytes")
        if provider not in ("bing_public_rss", "mediawiki_opensearch"):
            raise ValueError("unknown_provider")
        if user_agent is not None:
            if (type(user_agent) is not str or not 16 <= len(user_agent) <= 300
                    or not user_agent.isascii() or not user_agent.isprintable()
                    or "/" not in user_agent
                    or not ("http" in user_agent or "@" in user_agent)):
                raise ValueError("invalid_user_agent")
        if provider == "bing_public_rss":
            if search_endpoint is not None:
                raise ValueError("unexpected_search_endpoint")
            endpoint = None
            agent = user_agent or "MARCO2-Evidence/0.1"
        else:
            if user_agent is None:
                raise ValueError("missing_user_agent")
            if type(search_endpoint) is not str or not search_endpoint:
                raise ValueError("missing_search_endpoint")
            try:
                parts = urllib.parse.urlsplit(search_endpoint)
                parts.port
                public_url(search_endpoint)
            except (ValueError, RetrievalError) as exc:
                raise ValueError("invalid_search_endpoint") from exc
            if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                    or parts.password is not None or parts.query or parts.fragment
                    or "?" in search_endpoint or "#" in search_endpoint):
                raise ValueError("invalid_search_endpoint")
            endpoint = search_endpoint
            agent = user_agent
        self.timeout, self.max_bytes = timeout, max_bytes
        self._native_provider, self._search_endpoint, self._user_agent = provider, endpoint, agent
        self.provider = provider

    def _read(self, url, *, capture=None):
        if capture is not None and (type(capture) is not dict or capture):
            raise RetrievalError("capture_invalid")
        rec = {} if capture is None else capture
        started = time.monotonic()
        rec["started_at"] = datetime.now(timezone.utc).isoformat()
        outcome = "interrupted"
        try:
            try:
                url = public_url(url, resolve=True)
                rec["requested_url"] = url
                opener = urllib.request.build_opener(_PublicRedirects(),
                    urllib.request.HTTPSHandler(context=_tls_context()))
                req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
                with opener.open(req, timeout=self.timeout) as response:
                    rec["received_at"] = datetime.now(timezone.utc).isoformat()
                    status = getattr(response, "status", None)
                    if type(status) is int:
                        rec["http_status"] = status
                    final_url = public_url(response.geturl(), resolve=True)
                    rec["final_url"] = final_url
                    content_type = response.headers.get_content_type()
                    charset = response.headers.get_content_charset() or "utf-8"
                    rec["content_type"], rec["charset"] = content_type, charset
                    body = response.read(self.max_bytes + 1)
                    rec["bytes_read"] = len(body)
                    if len(body) > self.max_bytes:
                        rec["body_complete"] = False
                        rec["partial_body_sha256"] = hashlib.sha256(body).hexdigest()
                        raise RetrievalError("source_too_large")
                    rec["body_complete"] = True
                    rec["body_sha256"] = hashlib.sha256(body).hexdigest()
                    outcome = "success"
                    return {"body": body, "final_url": final_url,
                            "content_type": content_type, "charset": charset}
            except Exception as exc:
                outcome = "failed"
                code = _error(exc)["code"]
                rec["error_code"] = code if re.fullmatch(r"[a-z0-9_]{1,64}", code) else "retrieval_error"
                raise
        finally:
            rec["outcome"] = outcome
            rec["latency_seconds"] = time.monotonic() - started
            rec["completed_at"] = datetime.now(timezone.utc).isoformat()

    def search(self, terms, count, *, capture=None):
        if capture is not None and (type(capture) is not dict or capture):
            raise RetrievalError("capture_invalid")
        wiki = self._native_provider == "mediawiki_opensearch"
        if wiki:
            if type(terms) is not str or not terms.strip() or len(terms) > 500:
                raise RetrievalError("search_terms_invalid")
            if type(count) is not int or not 1 <= count <= 5:
                raise RetrievalError("search_count_invalid")
            params = {"action": "opensearch", "search": terms, "limit": count,
                      "namespace": 0, "redirects": "resolve", "format": "json"}
            url = self._search_endpoint + "?" + urllib.parse.urlencode(params)
        else:
            params = {"q": terms, "format": "rss"}
            url = "https://www.bing.com/search?" + urllib.parse.urlencode(params)
        if capture is not None:
            capture.update({
                "provider": self._native_provider,
                "scope": "selected_wiki_title_search" if wiki else "legacy_bing_public_rss",
                "general_web_search": not wiki,
                "fallback_used": False,
                "request": {"url": url, "params": dict(params)},
                "decode_status": "not_attempted", "results": [], "transport": None})
        transport = {}
        try:
            response = self._read(url) if capture is None else self._read(url, capture=transport)
        finally:
            if capture is not None:
                capture["transport"] = copy.deepcopy(transport)
        if wiki:
            try:
                rows, meta = _decode_mediawiki_opensearch(response["body"], count)
            except RetrievalError as exc:
                if capture is not None:
                    capture["decode_status"] = "failed:" + str(exc)
                raise
            if capture is not None:
                capture["decode_status"] = "ok"
                capture["protocol"] = meta
                capture["results"] = [dict(row) for row in rows]
            return rows
        try:
            root = ET.fromstring(response["body"])
        except ET.ParseError as exc:
            if capture is not None:
                capture["decode_status"] = "failed:search_not_rss_or_blocked"
            raise RetrievalError("search_not_rss_or_blocked") from exc
        if root.tag != "rss":
            if capture is not None:
                capture["decode_status"] = "failed:search_not_rss_or_blocked"
            raise RetrievalError("search_not_rss_or_blocked")
        rows = []
        for item in root.findall("./channel/item"):
            link = item.findtext("link") or ""
            try:
                link = public_url(link)
            except RetrievalError:
                continue
            rows.append({"url": link, "title": item.findtext("title") or ""})
            if len(rows) >= count:
                break
        if capture is not None:
            capture["decode_status"] = "ok"
            capture["results"] = [dict(row) for row in rows]
        return rows

    def fetch(self, url, terms, sentence_limit, *, capture=None):
        response = self._read(url) if capture is None else self._read(url, capture=capture)
        kind = response["content_type"]
        if kind not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise RetrievalError("unsupported_content_type")
        try:
            text = response["body"].decode(response["charset"], "replace")
        except LookupError as exc:
            raise RetrievalError("unsupported_charset") from exc
        if kind == "text/plain":
            blocks, title = [text], ""
        else:
            match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            title = web.sanitize(match.group(1), max_n=300) if match else ""
            extractor = web._BodyExtractor()
            extractor.feed(text)
            blocks = extractor.emit_end()
        # Use the existing content-word path for English as well. The legacy
        # single-topic alias trimmer includes literal n/r/t in its punctuation
        # set, which can trim the final letter of a name such as Python.
        related_terms = terms.split() if isinstance(terms, str) else terms
        related = web._related_verdict(related_terms)
        sentences = []
        for block in blocks:
            found = web.complete_sentences(block)
            if not found or not related(found):
                continue
            for sentence in found:
                if sentence not in sentences:
                    sentences.append(sentence)
                if len(sentences) >= sentence_limit:
                    break
            if len(sentences) >= sentence_limit:
                break
        return {"title": title, "final_url": response["final_url"], "sentences": sentences}


class SearchEvidenceService:
    """Normal dialogue adapter. No persistence, inference or approval side effects."""

    def __init__(self, backend=None):
        self.backend = backend if backend is not None else PublicWebBackend()
        # A custom callback/fixture cannot claim that it performed public HTTP.
        self.mode = "actual_web" if type(self.backend) is PublicWebBackend else "offline_fixture"

    def research(self, question, *, search_terms=None, limit=3, sentence_limit=12,
                 language_pack=None, meaning_reader=None, single_value_predicates=(), claim_limit=256):
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError("invalid_question")
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("invalid_source_limit")
        if type(sentence_limit) is not int or not 1 <= sentence_limit <= 48:
            raise ValueError("invalid_sentence_limit")
        if type(claim_limit) is not int or not 1 <= claim_limit <= 512:
            raise ValueError("invalid_claim_limit")
        if (not isinstance(single_value_predicates, (list, tuple, set, frozenset))
                or any(not isinstance(item, str) for item in single_value_predicates)):
            raise ValueError("invalid_single_value_predicates")
        terms = (web.question_word(question, language_pack) or question) if search_terms is None else search_terms
        if isinstance(terms, (list, tuple)):
            if not all(isinstance(term, str) for term in terms):
                raise ValueError("invalid_search_terms")
            query_terms = " ".join(terms)
        elif isinstance(terms, str):
            query_terms = terms
        else:
            raise ValueError("invalid_search_terms")
        if not query_terms.strip() or len(query_terms) > 500:
            raise ValueError("invalid_search_terms")
        started = time.monotonic()
        report = {"query": question, "search_terms": copy.deepcopy(terms), "mode": self.mode,
                  "verified": False, "evidence_status": "missing", "sources": [],
                  "observations": [], "claims": [], "conflicts": [],
                  "claim_limit": claim_limit, "claims_truncated": False,
                  "graph": {"nodes": [], "edges": []},
                  "limitations": ["retrieved_observations_are_not_verified_truth",
                                  "different_domains_do_not_prove_independence",
                                  "conflict_detection_requires_declared_roles_or_parsed_scoped_facts"],
                  "search": {"provider": getattr(self.backend, "provider", "injected_fixture"),
                             "searched_at": _utc(), "status": "pending", "error": None}}
        native = type(self.backend) is PublicWebBackend
        discovery = {}
        try:
            if native:
                hits = list(islice(self.backend.search(query_terms, limit, capture=discovery), limit))
            else:
                hits = list(islice(self.backend.search(query_terms, limit), limit))
            report["search"]["status"] = "ok" if hits else "no_results"
        except Exception as exc:
            hits = []
            report["search"].update(status="failed", error=_error(exc))
        finally:
            if native:
                report["search"]["discovery"] = copy.deepcopy(discovery)
                for key in ("scope", "general_web_search"):
                    if key in discovery:
                        report["search"][key] = copy.deepcopy(discovery[key])
        report["search"]["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        seen = set()
        for hit in hits:
            try:
                url = public_url(hit["url"])
            except (RetrievalError, KeyError, TypeError) as exc:
                report.setdefault("rejected_hits", []).append({"error": _error(exc)})
                continue
            if url in seen:
                continue
            seen.add(url)
            source = {"id": _id("source", url), "url": url, "final_url": None,
                      "domain": urllib.parse.urlsplit(url).hostname, "title": "",
                      "status": "pending", "fetched_at": _utc(), "error": None,
                      "sentences": [], "coverage_sentences": []}
            fetch_start = time.monotonic()
            transport = {}
            try:
                if native:
                    fetched = self.backend.fetch(url, terms, sentence_limit, capture=transport)
                else:
                    fetched = self.backend.fetch(url, terms, sentence_limit)
                final_url = public_url(fetched.get("final_url") or url)
                rows = fetched["sentences"]
                if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
                    raise RetrievalError("invalid_source_sentences")
                # Complete source sentences only; never a discovery snippet.
                sentences = list(dict.fromkeys(row for row in rows
                    if row in web.complete_sentences(row)))[:sentence_limit]
                source.update(final_url=final_url, domain=urllib.parse.urlsplit(final_url).hostname,
                              title=web.sanitize(fetched.get("title") or "", max_n=300),
                              status="ok" if sentences else "no_complete_related_sentences",
                              sentences=sentences, coverage_sentences=sentences)
            except Exception as exc:
                source.update(status="failed", error=_error(exc))
            finally:
                if native:
                    source["transport"] = copy.deepcopy(transport)
            source["latency_ms"] = round((time.monotonic() - fetch_start) * 1000, 3)
            report["sources"].append(source)
            report["graph"]["nodes"].append({"id": source["id"], "kind": "source",
                "url": source["final_url"] or url, "fetched_at": source["fetched_at"], "status": source["status"]})
            for sentence in source["sentences"]:
                observation = {"id": _id("observation", source["id"], sentence), "text": sentence,
                    "source_id": source["id"], "observed_at": source["fetched_at"],
                    "scope": {"query": question, "topic": copy.deepcopy(terms)},
                    "status": "observed", "trusted": False}
                report["observations"].append(observation)
                report["graph"]["nodes"].append({**copy.deepcopy(observation), "kind": "observation"})
                report["graph"]["edges"].append({"source": observation["id"], "target": source["id"],
                                                  "relation": "provenance"})
                if meaning_reader is not None:
                    if len(report["claims"]) >= claim_limit:
                        report["claims_truncated"] = True
                    else:
                        self._read_meaning(report, observation, meaning_reader)
        successful = [source for source in report["sources"] if source["status"] == "ok"]
        report["coverage"] = web.evidence_coverage(question, terms, successful, language_pack)
        for kind, sources in report["coverage"]["conflicts"].items():
            if sources:
                report["conflicts"].append({"kind": "declared_role_conflict", "role": kind,
                                            "sources": copy.deepcopy(sources)})
        self._conflicts(report, set(single_value_predicates))
        if report["conflicts"]:
            report["evidence_status"] = "conflicting_observations"
        elif report["observations"]:
            report["evidence_status"] = "observed"
            if report["coverage"]["required"] and report["coverage"]["resolved"]:
                report["evidence_status"] = "role_corroborated_observations"
        report["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        return report

    @staticmethod
    def _read_meaning(report, observation, reader):
        try:
            parsed = reader(observation["text"])
            facts = (parsed or {}).get("facts", [])
            if not isinstance(facts, list):
                raise RetrievalError("invalid_meaning_facts")
            for fact in facts[:48]:
                triple = fact.get("triple")
                if (not isinstance(triple, (list, tuple)) or len(triple) != 3
                        or any(not isinstance(item, str) or not item for item in triple)
                        or type(fact.get("polarity", True)) is not bool
                        or fact.get("modality", "asserted") != "asserted"):
                    continue
                claim = {"id": _id("claim", observation["id"], triple, fact.get("scope"),
                                   fact.get("polarity", True)), "triple": list(triple),
                         "polarity": fact.get("polarity", True), "scope": copy.deepcopy(fact.get("scope")),
                         "observation_id": observation["id"], "source_id": observation["source_id"],
                         "evidence": {"text": observation["text"]}, "status": "observed", "trusted": False}
                if any(row["id"] == claim["id"] for row in report["claims"]):
                    continue
                if len(report["claims"]) >= report["claim_limit"]:
                    report["claims_truncated"] = True
                    break
                report["claims"].append(claim)
                report["graph"]["nodes"].append({**copy.deepcopy(claim), "kind": "parsed_claim"})
                report["graph"]["edges"].append({"source": claim["id"], "target": observation["id"],
                                                  "relation": "parsed_from"})
        except Exception as exc:
            observation["meaning_error"] = _error(exc)

    @staticmethod
    def _conflicts(report, single_value_predicates):
        claims = report["claims"]
        for index, left in enumerate(claims):
            for right in claims[index + 1:]:
                if left["scope"] != right["scope"]:
                    continue
                same_triple = left["triple"] == right["triple"]
                polarity = same_triple and left["polarity"] != right["polarity"]
                values = (left["scope"] is not None and left["triple"][:2] == right["triple"][:2]
                          and left["triple"][1] in single_value_predicates
                          and left["triple"][2] != right["triple"][2]
                          and left["polarity"] and right["polarity"])
                if not polarity and not values:
                    continue
                conflict = {"kind": "opposed_polarity" if polarity else "scoped_value_disagreement",
                            "claims": [left["id"], right["id"]], "scope": copy.deepcopy(left["scope"]),
                            "resolution": "requires_scope_check" if left["scope"] is None else "requires_review"}
                report["conflicts"].append(conflict)
                report["graph"]["edges"].append({"source": left["id"], "target": right["id"],
                                                  "relation": "conflicts_with"})
