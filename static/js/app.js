/* Barris & Zarzuelo – small helpers only. All real logic stays in the Flask app. */
(function () {
  // Dismiss flash messages
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.alert-close');
    if (btn) {
      var a = btn.closest('.alert');
      if (a) a.remove();
    }
  });

  // Dropzone drag highlight (visual only – real upload uses the underlying <input type=file>)
  document.querySelectorAll('.dropzone').forEach(function (dz) {
    ['dragenter', 'dragover'].forEach(function (ev) {
      dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add('dragging'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove('dragging'); });
    });
  });

  // Radio segmented control (visual only)
  document.querySelectorAll('.radio-group').forEach(function (g) {
    g.addEventListener('click', function (e) {
      var opt = e.target.closest('.radio-opt');
      if (!opt) return;
      g.querySelectorAll('.radio-opt').forEach(function (o) { o.classList.remove('on'); });
      opt.classList.add('on');
    });
  });
})();
