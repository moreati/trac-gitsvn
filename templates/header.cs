<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
        "http://www.w3.org/TR/2000/REC-xhtml1-20000126/DTD/xhtml1-strict.dtd">

<?cs def:navlink(text, href, id, aclname) ?>
  <?cs if $trac.acl.+aclname ?>
      <a href="<?cs var:href ?>" class="navbar-link<?cs if $id == $trac.active_module ?>-active<?cs /if ?>"><?cs var:text ?></a>
    <span class="hide"> | </span>
  <?cs /if ?>
<?cs /def ?>
<html>
  <head>
    <?cs if $project.name ?>
      <title>Trac | <?cs var:project.name?> | <?cs var:title ?></title>
    <?cs else ?>
      <title>Trac | <?cs var:title ?></title>
    <?cs /if ?>
    <style type="text/css">
      <!--
      @import url("<?cs var:$htdocs_location ?>/css/trac.css");
      <?cs if:trac.active_module == 'browser' ?>
      @import url("<?cs var:$htdocs_location ?>/css/browser.css");
      <?cs elif:trac.active_module == 'timeline' ?>
      @import url("<?cs var:$htdocs_location ?>/css/timeline.css");
      <?cs elif:trac.active_module == 'changeset' ?>
      @import url("<?cs var:$htdocs_location ?>/css/changeset.css");
      <?cs elif:trac.active_module == 'newticket' || trac.active_module == 'ticket' ?>
      @import url("<?cs var:$htdocs_location ?>/css/ticket.css");
      <?cs /if ?>
      /* Dynamically/template-generated CSS below */
      #navbar { background: url("<?cs var:$htdocs_location ?>/topbar_gradient.png") top left #eee }  
      a.navbar-link { background: url(<?cs var:$htdocs_location ?>/dots.gif) top left no-repeat; }
       -->
    </style>
</head>
<body>

<div id="header">
  <a id="hdrlogo" href="<?cs var:header_logo.link ?>"><img src="<?cs var:header_logo.src ?>" 
      width="<?cs var:header_logo.width ?>" 
      height="<?cs var:header_logo.height ?>" 
      alt="<?cs var:header_logo.alt ?>" /></a>
  <hr class="hide"/>
  <div id="header-links">
    <?cs if $trac.authname == "anonymous" ?>
      <a href="<?cs var:trac.href.login ?>" 
         class="navbar-link-right">Login</a>&nbsp;| 
    <?cs else ?> 
      logged in as <?cs var:trac.authname ?>&nbsp;| 
      <a href="<?cs var:trac.href.logout ?>" 
         class="navbar-link-right"> Logout </a>&nbsp;| 
    <?cs /if ?>
    <a href="<?cs var:trac.href.wiki ?>TracGuide" 
       class="navbar-link-right"> Help/Guide </a>&nbsp;| 
    <a href="<?cs var:trac.href.about ?>" 
       class="navbar-link-right"> About Trac </a>
  </div>
  <div id="navbar">
    <div id="navbar-links">
      <?cs call:navlink("Wiki", $trac.href.wiki, "wiki", 
                        "WIKI_VIEW") ?>
      <?cs call:navlink("Browser", $trac.href.browser, "browser", 
                        "BROWSER_VIEW") ?>
      <?cs call:navlink("Timeline", $trac.href.timeline, "timeline", 
                        "TIMELINE_VIEW") ?>
      <?cs call:navlink("Reports", $trac.href.report, "report", 
                        "REPORT_VIEW") ?>
      <?cs call:navlink("Search", $trac.href.search, "search", 
                        "SEARCH_VIEW") ?>
      <?cs call:navlink("New Ticket", $trac.href.newticket, "newticket", 
                        "TICKET_CREATE") ?>
    </div>
  </div>
</div>
