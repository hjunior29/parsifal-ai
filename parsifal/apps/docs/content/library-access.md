# Open studies through CAPES

With **Settings → Library access**, the study window gets a **Via CAPES** link
next to *External Link*. It opens the study at the publisher with your
institution's access, the same way the CAPES *Portal de Periódicos* does when
you are signed in through **Acesso CAFe**: no paywall for what your institution
subscribes to.

Parsifal never signs in to CAPES and never sees your login. It only writes the
link; your browser, already signed in, does the rest.

## How it works

Signed in to CAPES through CAFe, your browser reaches the publishers at an
address of your institution: the publisher's address with its dots turned into
hyphens, followed by your institution's part (here `ezNN`, a number that
depends on the institution):

```
https://ieeexplore.ieee.org/document/1234567
https://ieeexplore-ieee-org.ezNN.periodicos.capes.gov.br/document/1234567
```

Parsifal builds the same kind of address for each study:

```
1. You sign in, once     you ──Acesso CAFe──► CAPES
                         the browser keeps the session of *.ezNN.periodicos.capes.gov.br

2. Parsifal writes       Via CAPES = https://doi-org.ezNN.periodicos.capes.gov.br/10.1109/…
   the link              (the study's DOI, through your institution's address)

3. You click it          the browser sends its session ──► CAPES ──► doi.org ──► the publisher,
                         with your institution's access
```

The link uses the study's **DOI** when it has one: doi.org takes you to the
publisher's page, still through CAPES. That works for studies from any source,
including Scopus and Web of Science, whose own links open their record pages
rather than the article. Without a DOI, the link is the study's URL through
CAPES.

| The study has | External Link opens | Via CAPES opens |
|---------------|--------------------|-----------------|
| a DOI | its URL, or the DOI at doi.org | the DOI through CAPES: `doi-org.ezNN…/10.1109/X.1` |
| a URL, no DOI | the URL | the URL through CAPES: `www-scopus-com.ezNN…/record/1` |
| neither | — | — |

## Set it up

1. Sign in at [www.periodicos.capes.gov.br](https://www.periodicos.capes.gov.br)
   with **Acesso CAFe** (choose your institution and use its login).
2. Open any study at the publisher through the portal — or any link you already
   have that goes through CAPES.
3. Copy the address from the browser's address bar.
4. In Parsifal, go to **Settings → Library access**, paste it and save.

Parsifal keeps only your institution's part (`ezNN.periodicos.capes.gov.br`);
the page shows what it kept. You can also paste that part directly. The address
of the portal itself (`www.periodicos.capes.gov.br`) is not accepted: it does
not say which institution's access to use.

The setting is yours, not the review's: each member sets their own, so a
co-author at another institution uses theirs, or none.

## When you click Via CAPES

- **Signed in**: the publisher's page opens with your institution's access.
- **Not signed in** (or the session expired): CAPES asks you to sign in. If it
  does not take you to the study afterwards, click *Via CAPES* again.
- **A journal your institution does not subscribe to**: the publisher's page
  opens without access, as with *External Link*.

No link is shown for a study with neither a DOI nor a URL, nor for one without
a DOI whose URL's address has hyphens of its own (how CAPES rewrites those is
not documented, so Parsifal gives no link rather than a wrong one).

Studies exported from a publisher while you were signed in may already carry a
CAPES address as their URL (ACM's exports do): their *External Link* already
goes through CAPES.

## What Parsifal keeps

Only the proxy's address. Not your CAFe login, not your session, not the
studies: Parsifal does not download anything from CAPES or the publishers (the
portal's terms do not allow robots or systematic downloads). The link is opened
by your browser, as if you had clicked it on the portal.

Another library's EZproxy works the same way when it serves the publishers at
addresses with hyphens: paste the address of a page opened through it, and the
link is called **Via proxy**.

## API, CLI and MCP

- API: `GET`, `PUT {address}` and `DELETE /api/v1/integrations/library-access`.
  Every study the API returns carries `access_url` (null without a proxy).
- CLI: `parsifal integration library-access set --address "https://…"`, `show`,
  `remove`; `parsifal article get` shows `access_url`.
- MCP: `parsifal_library_access_get`, `parsifal_library_access_set`,
  `parsifal_library_access_delete`.
