// Enable expanding/folding folders in TracBrowser

var counter = 0;

function enableExpandDir(elem) {
  elem.find("span.direxpand").css("cursor", "pointer").click(toggleDir);
}

function toggleDir() {
  var td = $(this).parent();
  if ( $(this).attr("class") == "direxpand" ) {
    $(this).attr("class", "dirfold").attr("title", "Fold directory");
    expandDir(td);
  } else {
    $(this).attr("class", "direxpand").attr("title", "Expand directory");
    foldDir(td);
  }
}

function expandDir(td) {
  var tr = td.parent();
  var folderid_match = /f\d+/.exec(td.attr("class"));

  if (folderid_match) { // then simply re-expand collapsed folder
    tr.siblings("tr."+folderid_match[0]).toggle();
    return;
  }

  var a = td.children("a");
  var href = a.attr("href");
  var depth = parseFloat(td.css("padding-left").replace(/^(\d*\.\d*).*$/, "$1")) + 20;

  // insert "Loading ..." row
  tr.after('<tr><td class="name" colspan="5" style="padding-left: ' +
	   depth + 'px"><span class="loading">Loading ' + a.text() +
	   '...</span></td></tr>');

  // prepare the class that will be used by foldDir to identify all the 
  // rows to be removed when collapsing that folder
  var folderid = "f" + counter++;
  td.addClass(folderid);
  var ancestor_folderids = $.grep(tr.attr("class").split(" "), 
				  function(c) { return c.match(/^f\d+$/)});
  ancestor_folderids.push(folderid);

  $.get(href, {action: "inplace"}, function(data) {
    // remove "Loading ..." row
    tr.next().remove();
    // insert folder content rows
    var rows = $(data.replace(/^<!DOCTYPE[^>]+>/, "")).filter("tr");
    rows.addClass(ancestor_folderids.join(" "));
    rows.children("td.name").css("padding-left", depth);
    enableExpandDir(rows);
    tr.after(rows);
  });
}

function foldDir(td) {
  var folderid = /f\d+/.exec(td.attr("class"))[0];
  td.parent().siblings("tr."+folderid).toggle();
}